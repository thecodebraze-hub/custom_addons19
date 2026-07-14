/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";

export class VoucherScanner extends Component {
    static template = "cb_pos_return_exchange.VoucherScanner";
    static components = { Dialog };
    static props = {
        pos: { type: Object },
        barcode: { type: String, optional: true },
        paymentMode: { type: Boolean, optional: true },
        order: { type: Object, optional: true },
        getPayload: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.api = this.props.pos.returnApi;
        this.voucherPayment = this.props.pos.voucherPayment;
        this.barcodeHandler = this.props.pos.returnBarcode;
        this.order = this.props.order || this.props.pos.getOrder();
        this.inputRef = useRef("barcodeInput");
        this.state = useState({
            barcode: this.props.barcode || "",
            voucher: null,
            amount: 0,
            customerBalance: 0,
            loading: false,
            error: "",
            issueRemainder: false,
        });

        useBarcodeReader(this.barcodeHandler.buildCallbackMap(this), true);

        onMounted(async () => {
            this.barcodeHandler.setMode("voucher");
            this.unregisterBarcode = this.barcodeHandler.setExclusive((code) =>
                this.onBarcodeScanned(code)
            );
            this.inputRef.el?.focus();
            if (this.state.barcode) {
                await this.validate();
            }
        });

        onWillUnmount(() => {
            this.unregisterBarcode?.();
        });
    }

    formatMoney(amount) {
        return this.api.formatMoney(amount);
    }

    async onBarcodeScanned(code) {
        this.state.barcode = code;
        await this.validate();
    }

    async onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            await this.validate();
        }
    }

    async validate() {
        this.state.error = "";
        const code = (this.state.barcode || "").trim();
        if (!code) {
            this.state.error = _t("Scan a voucher barcode.");
            return;
        }
        this.state.loading = true;
        try {
            const result = this.props.paymentMode
                ? await this.voucherPayment.validateForPayment(this.order, code)
                : await this.api.validateVoucher(code);
            if (!result?.success) {
                this.state.voucher = result.voucher || null;
                this.state.error = result?.error || _t("Voucher not found.");
                return;
            }
            const voucher = result.voucher;
            if (!voucher.is_redeemable && !voucher.valid) {
                this.state.error =
                    voucher.validation_message || _t("Voucher is not redeemable.");
            }
            this.state.voucher = voucher;
            this.state.customerBalance = Number(result.customer_balance) || 0;
            const suggested = this.voucherPayment.computeApplyAmount(
                this.order,
                voucher.amount_remaining
            );
            this.state.amount = suggested;
            // Direct add: as soon as a redeemable voucher is validated, apply
            // it and close, instead of requiring a separate "Apply" click.
            if (this.props.paymentMode && voucher.is_redeemable && this.state.amount > 0) {
                await this.apply();
            }
        } finally {
            this.state.loading = false;
        }
    }

    async apply() {
        if (!this.state.voucher?.is_redeemable) {
            this.state.error = _t("Voucher is not redeemable.");
            return;
        }
        if (!this.order) {
            this.state.error = _t("No active order.");
            return;
        }
        const amount = Number(this.state.amount) || 0;
        if (amount <= 0) {
            this.state.error = _t("Amount must be greater than zero.");
            return;
        }

        const result = await this.voucherPayment.applyVoucher(this.order, this.state.voucher, {
            amount,
            issueRemainder: this.state.issueRemainder,
        });
        if (!result?.success) {
            this.state.error = result?.error || _t("Unable to apply voucher.");
            return;
        }

        if (this.props.paymentMode) {
            const partner = this.order.getPartner?.();
            if (partner?.id) {
                this.voucherPayment.clearCustomerBalanceCache(partner.id);
            }
        }

        this.props.getPayload({
            action: "voucher_applied",
            voucher: this.state.voucher,
            amount: result.amount,
            entry: result.entry,
        });
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
