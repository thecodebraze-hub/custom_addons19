/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import { useState, onMounted } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PaymentVouchersPanel } from "../../components/payment_vouchers_panel/payment_vouchers_panel";
import "../../load_services";

PaymentScreen.components = {
    ...PaymentScreen.components,
    PaymentVouchersPanel,
};

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        // The dedicated return-voucher tender is applied only through the
        // "Scan Voucher" flow, so hide it from the manual payment-method list.
        this.payment_methods_from_config = this.payment_methods_from_config.filter(
            (pm) => !pm.cb_is_voucher_method
        );
        this.cbVoucherUi = useState({
            customerBalance: 0,
            revision: 0,
        });

        useBarcodeReader({
            product: (parsed) => this.onCbVoucherBarcodeScan(parsed),
            weight: (parsed) => this.onCbVoucherBarcodeScan(parsed),
            quantity: (parsed) => this.onCbVoucherBarcodeScan(parsed),
            price: (parsed) => this.onCbVoucherBarcodeScan(parsed),
            gs1: (parsed) => {
                const product = parsed?.find?.((p) => p.type === "product");
                if (product) {
                    this.onCbVoucherBarcodeScan(product);
                }
            },
        });

        onMounted(() => {
            this.refreshCbCustomerBalance();
        });
    },

    _bumpCbVoucherUi() {
        this.cbVoucherUi.revision += 1;
    },

    get cbVoucherLines() {
        void this.cbVoucherUi.revision;
        return this.pos.voucherPayment.getVouchers(this.currentOrder);
    },

    formatCbMoney(amount) {
        return this.pos.returnApi.formatMoney(amount);
    },

    async refreshCbCustomerBalance() {
        const partner = this.currentOrder?.getPartner?.();
        if (!partner?.id) {
            this.cbVoucherUi.customerBalance = 0;
            return;
        }
        this.cbVoucherUi.customerBalance = await this.pos.voucherPayment.fetchCustomerBalance(
            partner.id
        );
    },

    async onCbVoucherBarcodeScan(parsed) {
        const code = this.pos.returnBarcode.extractCode(parsed, parsed?.code);
        if (!code) {
            return;
        }
        const validate = await this.pos.voucherPayment.validateForPayment(
            this.currentOrder,
            code
        );
        if (validate?.success) {
            await this.applyCbVoucherBarcode(code, { promptPartial: true });
            return;
        }
        if (validate?.error_code === "duplicate_voucher") {
            this.notification.add(validate.error, { type: "warning" });
            return;
        }
        await this.pos.returnBarcode.processScan(parsed, { screen: "payment" });
    },

    async applyCbVoucherBarcode(barcode, { promptPartial = false } = {}) {
        const result = await this.pos.applyVoucherFromPaymentScan(barcode, { promptPartial });
        if (result?.success) {
            this._bumpCbVoucherUi();
            await this.refreshCbCustomerBalance();
        }
        return result;
    },

    removeCbVoucher(entryUuid) {
        this.pos.voucherPayment.removeVoucher(this.currentOrder, entryUuid);
        this._bumpCbVoucherUi();
        this.refreshCbCustomerBalance();
    },

    deletePaymentLine(uuid) {
        // Deleting a voucher's payment line (via the standard "x") must also
        // drop the pending voucher entry, so it is NOT redeemed on validation.
        const entry = this.pos.voucherPayment
            .getVouchers(this.currentOrder)
            .find((v) => v.payment_line_uuid === uuid);
        if (entry) {
            this.pos.voucherPayment.removeVoucher(this.currentOrder, entry.uuid);
            this._bumpCbVoucherUi();
            this.refreshCbCustomerBalance();
            this.numberBuffer?.reset?.();
            return;
        }
        return super.deletePaymentLine(uuid);
    },

    async validateOrder(isForceValidate = false) {
        // A return voucher may never be worth more than the bill: the order
        // total must be at least the applied voucher amount (equal is allowed),
        // so no cash is ever refunded through an exchange.
        const voucherApplied = this.pos.voucherPayment.getTotalApplied(this.currentOrder);
        if (voucherApplied > 0) {
            const currency = this.currentOrder.currency;
            const orderTotal = this.currentOrder.totalDue;
            const diff = currency.round(orderTotal - voucherApplied);
            if (diff < 0) {
                const needed = currency.round(voucherApplied - orderTotal);
                this.pos.dialog.add(AlertDialog, {
                    title: _t("Add more products"),
                    body: _t(
                        "The bill must be at least the return voucher (%s). Add products worth at least %s more.",
                        this.pos.returnApi.formatMoney(voucherApplied),
                        this.pos.returnApi.formatMoney(needed)
                    ),
                });
                return;
            }
        }
        return super.validateOrder(isForceValidate);
    },

    async clickCbScanVoucher() {
        const result = await this.pos.openVoucherScanner({
            paymentMode: true,
            order: this.currentOrder,
        });
        if (result?.action === "voucher_applied") {
            this._bumpCbVoucherUi();
            await this.refreshCbCustomerBalance();
        }
    },

    get showCbVoucherButton() {
        return this.pos.cashier?._role !== "minimal";
    },
});
