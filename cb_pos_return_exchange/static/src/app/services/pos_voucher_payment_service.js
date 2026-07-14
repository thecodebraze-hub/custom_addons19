/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";

/**
 * Manages multiple voucher redemptions on a POS order at payment time.
 */
export class PosVoucherPaymentService {
    constructor(pos) {
        this.pos = pos;
        this._customerBalanceCache = new Map();
    }

    getVouchers(order) {
        if (!order) {
            return [];
        }
        if (!order.cbReturnVouchers) {
            order.cbReturnVouchers = [];
        }
        return order.cbReturnVouchers;
    }

    getAppliedVoucherIds(order) {
        return this.getVouchers(order).map((v) => v.voucher_id);
    }

    hasVoucher(order, voucherId, barcode) {
        return this.getVouchers(order).some(
            (entry) =>
                entry.voucher_id === voucherId ||
                (barcode && entry.barcode === barcode)
        );
    }

    getTotalApplied(order) {
        return this.getVouchers(order).reduce(
            (sum, entry) => sum + (Number(entry.amount) || 0),
            0
        );
    }

    getRemainingOrderDue(order) {
        return Math.max(Number(order?.remainingDue) || 0, 0);
    }

    computeApplyAmount(order, voucherRemaining, requestedAmount = null) {
        const due = this.getRemainingOrderDue(order);
        if (due <= 0) {
            return 0;
        }
        const maxVoucher = Math.max(Number(voucherRemaining) || 0, 0);
        if (requestedAmount != null) {
            return Math.min(Math.max(Number(requestedAmount) || 0, 0), maxVoucher, due);
        }
        return Math.min(maxVoucher, due);
    }

    getVoucherPaymentMethod() {
        const methods = this.pos.config.payment_method_ids || [];
        return (
            methods.find((pm) => pm.cb_is_voucher_method) ||
            methods.find((pm) => pm.name && pm.name.toLowerCase().includes("voucher")) ||
            methods.find((pm) => !pm.payment_terminal && !pm.is_cash_count) ||
            methods[0]
        );
    }

    async fetchCustomerBalance(partnerId) {
        if (!partnerId) {
            return 0;
        }
        if (this._customerBalanceCache.has(partnerId)) {
            return this._customerBalanceCache.get(partnerId);
        }
        const result = await this.pos.returnApi.getCustomerVoucherBalance(partnerId);
        const balance = result?.success ? Number(result.customer_balance) || 0 : 0;
        this._customerBalanceCache.set(partnerId, balance);
        return balance;
    }

    clearCustomerBalanceCache(partnerId = null) {
        if (partnerId) {
            this._customerBalanceCache.delete(partnerId);
        } else {
            this._customerBalanceCache.clear();
        }
    }

    async validateForPayment(order, barcode) {
        const partner = order?.getPartner?.();
        return this.pos.returnApi.validateVoucherPayment(barcode, {
            partnerId: partner?.id || false,
            appliedVoucherIds: this.getAppliedVoucherIds(order),
        });
    }

    async promptPartialAmount(voucher, maxAmount) {
        const settings = await this.pos.returnApi.getSettings();
        const allowPartial = settings?.settings?.allow_partial_voucher_redemption !== false;
        if (!allowPartial || maxAmount <= 0) {
            return maxAmount;
        }
        const input = await makeAwaitable(this.pos.dialog, NumberPopup, {
            title: _t("Voucher amount to apply"),
            startingValue: maxAmount,
        });
        if (input === undefined) {
            return null;
        }
        return Math.min(Math.max(Number(input) || 0, 0), maxAmount, voucher.amount_remaining);
    }

    addPaymentLine(order, amount) {
        const paymentMethod = this.getVoucherPaymentMethod();
        if (!paymentMethod) {
            return { success: false, error: _t("No payment method available for vouchers.") };
        }
        const result = order.addPaymentline(paymentMethod);
        if (!result?.status) {
            return {
                success: false,
                error: result?.data || _t("Unable to add voucher payment line."),
            };
        }
        const line = result.data;
        line.setAmount(amount);
        // Treat the voucher as a settled manual tender (like cash). Leaving the
        // payment status empty avoids the electronic-terminal flow ("Request
        // sent" / "Force done") and the "electronic payment in progress" lock
        // that would otherwise block adding a second payment line.
        return { success: true, line };
    }

    async applyVoucher(order, voucher, { amount, issueRemainder = false, promptPartial = false } = {}) {
        if (!order) {
            return { success: false, error: _t("No active order.") };
        }
        if (this.hasVoucher(order, voucher.id, voucher.barcode)) {
            return {
                success: false,
                error_code: "duplicate_voucher",
                error: _t("This voucher is already applied to this order."),
            };
        }

        const settings = await this.pos.returnApi.getSettings();
        if (
            settings?.settings?.allow_multiple_voucher_usage === false &&
            this.getVouchers(order).length > 0
        ) {
            return {
                success: false,
                error_code: "multiple_vouchers_not_allowed",
                error: _t("Only one voucher can be used per order."),
            };
        }

        let applyAmount = this.computeApplyAmount(order, voucher.amount_remaining, amount);
        if (applyAmount <= 0) {
            return {
                success: false,
                error: _t("Order is already fully paid."),
            };
        }

        const isPartialOnVoucher =
            applyAmount < Number(voucher.amount_remaining || 0) - 0.0001;
        if (promptPartial && isPartialOnVoucher) {
            const chosen = await this.promptPartialAmount(voucher, applyAmount);
            if (chosen === null) {
                return { success: false, cancelled: true };
            }
            applyAmount = chosen;
        }

        const paymentResult = this.addPaymentLine(order, applyAmount);
        if (!paymentResult.success) {
            return paymentResult;
        }

        const remainingOnVoucher = Math.max(
            Number(voucher.amount_remaining || 0) - applyAmount,
            0
        );
        const entry = {
            uuid: crypto.randomUUID(),
            voucher_id: voucher.id,
            barcode: voucher.barcode,
            name: voucher.name,
            amount: applyAmount,
            voucher_amount: Number(voucher.amount) || 0,
            voucher_remaining: remainingOnVoucher,
            partner_id: voucher.partner_id,
            partner_name: voucher.partner_name,
            issue_remainder: issueRemainder,
            redeemed: false,
            payment_line_uuid: paymentResult.line.uuid,
        };
        this.getVouchers(order).push(entry);

        return {
            success: true,
            entry,
            amount: applyAmount,
            remaining_on_voucher: remainingOnVoucher,
        };
    }

    async applyFromBarcode(order, barcode, { promptPartial = false } = {}) {
        const validation = await this.validateForPayment(order, barcode);
        if (!validation?.success) {
            return validation;
        }
        return this.applyVoucher(order, validation.voucher, {
            amount: null,
            issueRemainder: false,
            promptPartial,
            customer_balance: validation.customer_balance,
        });
    }

    removeVoucher(order, entryUuid) {
        const vouchers = this.getVouchers(order);
        const index = vouchers.findIndex((v) => v.uuid === entryUuid);
        if (index < 0) {
            return false;
        }
        const entry = vouchers[index];
        if (entry.payment_line_uuid) {
            const line = order.getPaymentlineByUuid(entry.payment_line_uuid);
            if (line) {
                order.removePaymentline(line);
            }
        }
        vouchers.splice(index, 1);
        return true;
    }

    getSummary(order) {
        const vouchers = this.getVouchers(order);
        const totalApplied = this.getTotalApplied(order);
        const totalRemainingOnVouchers = vouchers.reduce(
            (sum, v) => sum + (Number(v.voucher_remaining) || 0),
            0
        );
        return {
            vouchers,
            count: vouchers.length,
            total_applied: totalApplied,
            total_voucher_remaining: totalRemainingOnVouchers,
            order_due: this.getRemainingOrderDue(order),
        };
    }
}
