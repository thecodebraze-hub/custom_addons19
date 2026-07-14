/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { PosReturnApiService } from "./pos_return_api_service";
import { PosVoucherPaymentService } from "./pos_voucher_payment_service";
import { CbReturnBarcodeHandler } from "./barcode_handler";
import { ReturnPopup } from "../components/popups/return_popup/return_popup";
import { VoucherPopup } from "../components/popups/voucher_popup/voucher_popup";
import { VoucherScanner } from "../components/popups/voucher_scanner/voucher_scanner";
import { HistoryPopup } from "../components/popups/history_popup/history_popup";
import { ReturnReceipt } from "../components/receipts/return_receipt";
import { VoucherReceipt } from "../components/receipts/voucher_receipt";

patch(PosStore.prototype, {
    async setup(...args) {
        this.returnApi = new PosReturnApiService(this);
        this.voucherPayment = new PosVoucherPaymentService(this);
        this.returnBarcode = new CbReturnBarcodeHandler(this);
        this._cbLastReturnId = false;
        this._cbPendingExchange = false;
        this._cbReturnModuleEnabled = true;
        await super.setup(...args);
        this._registerGlobalBarcodeListener();
        this._loadReturnModuleSettings();
    },

    async _loadReturnModuleSettings() {
        try {
            const result = await this.returnApi.getSettings();
            this._cbReturnModuleEnabled = result?.settings?.module_enabled !== false;
        } catch {
            this._cbReturnModuleEnabled = true;
        }
    },

    _getBarcodeScreenContext() {
        const page = this.router?.state?.current;
        if (page === "PaymentScreen") {
            return "payment";
        }
        if (page === "TicketScreen") {
            return "ticket";
        }
        if (page === "CbReturnScreen") {
            return "return";
        }
        if (page === "ProductScreen") {
            return "product";
        }
        return "other";
    },

    _registerGlobalBarcodeListener() {
        if (!this.barcodeReader || this._cbGlobalBarcodeUnregister) {
            return;
        }
        const onScan = async (parsed) => {
            if (!this._cbReturnModuleEnabled || this.returnBarcode._exclusive) {
                return;
            }
            const screen = this._getBarcodeScreenContext();
            if (screen === "product" || screen === "payment") {
                return;
            }
            await this.returnBarcode.processScan(parsed, { screen });
        };
        this._cbGlobalBarcodeUnregister = this.barcodeReader.register(
            {
                product: onScan,
                weight: onScan,
                quantity: onScan,
                price: onScan,
                gs1: async (parsed) => {
                    const product = parsed?.find?.((p) => p.type === "product");
                    if (product) {
                        await onScan(product);
                    }
                },
            },
            false
        );
    },

    _cbReturnScreenParams(params = {}) {
        // Neutral Return/Exchange: the screen lets the cashier pick the
        // settlement (voucher, cash, store credit, or exchange).
        return { ...params };
    },

    async openExchangeFlow() {
        const settings = await this.returnApi.getSettings();
        if (!this.returnBarcode.guardPermission(settings, "create_return")) {
            return;
        }
        // Hybrid flow: the popup handles search + order/product selection,
        // then hands off to the full Return/Exchange screen to confirm.
        const result = await makeAwaitable(this.dialog, ReturnPopup, {
            pos: this,
        });
        if (!result) {
            return;
        }
        if (result.action === "barcode" && result.code) {
            // Voucher / return-document barcode detected in the popup. The popup
            // is now closed, so its exclusive handler is gone and the global
            // router can classify and present the correct action.
            await this.returnBarcode.processScan(
                { code: result.code },
                { screen: "other", force: true }
            );
            return;
        }
        if (result.action === "open_screen") {
            this.navigate(
                "CbReturnScreen",
                this._cbReturnScreenParams({ searchTerm: result.searchTerm || "" })
            );
            return;
        }
        if (result.action === "gift_voucher" && result.voucher) {
            // No-receipt / gift exchange: a standalone voucher was issued.
            // Show it (with print) so the customer can redeem it at payment.
            this.notification.add(
                _t("Exchange voucher issued: %(name)s", { name: result.voucher.name }),
                { type: "success" }
            );
            await this.showVoucherPopup(result.voucher);
            return;
        }
        if (result.action === "order_found") {
            this.navigate(
                "CbReturnScreen",
                this._cbReturnScreenParams({
                    orderId: result.order?.id,
                    order: result.order,
                })
            );
        }
    },

    async openReturnPopup() {
        return this.openExchangeFlow();
    },

    async openReturnFlow({ searchTerm } = {}) {
        const settings = await this.returnApi.getSettings();
        if (!this.returnBarcode.guardPermission(settings, "create_return")) {
            return;
        }
        this.navigate("CbReturnScreen", this._cbReturnScreenParams({ searchTerm: searchTerm || "" }));
    },

    async openReturnScreen(params = {}) {
        this.navigate("CbReturnScreen", this._cbReturnScreenParams(params));
    },

    async openExchangeScreen(params = {}) {
        this.navigate("CbExchangeScreen", params);
    },

    async openVoucherScanner(props = {}) {
        const settings = await this.returnApi.getSettings();
        if (!this.returnBarcode.guardPermission(settings, "redeem_voucher")) {
            return;
        }
        const onPayment = this.router?.state?.current === "PaymentScreen";
        const result = await makeAwaitable(this.dialog, VoucherScanner, {
            pos: this,
            paymentMode: onPayment || props.paymentMode,
            order: props.order || (onPayment ? this.getOrder() : undefined),
            ...props,
        });
        return result;
    },

    async showVoucherPopup(voucher, returnDoc = null) {
        const props = { pos: this, voucher };
        // `returnDoc` is an optional Object prop: Owl rejects a `null` value,
        // so only pass it when a return document is actually available.
        if (returnDoc) {
            props.returnDoc = returnDoc;
        }
        await makeAwaitable(this.dialog, VoucherPopup, props);
        const settings = await this.returnApi.getSettings();
        if (settings?.settings?.auto_print_voucher && voucher?.id) {
            await this.printVoucherReceipt(voucher.id);
        }
    },

    async printVoucherReceipt(voucherId) {
        // Print on the POS thermal printer (no PDF / wkhtmltopdf needed), the
        // same way the return receipt is printed.
        const receipt = await this.data.call(
            "cb.pos.return.voucher",
            "pos_get_voucher_receipt_data",
            [[voucherId]]
        );
        if (!receipt) {
            return;
        }
        const result = await this.printer.print(
            VoucherReceipt,
            { receipt },
            this.printOptions
        );
        if (result?.warningCode) {
            this.displayPrinterWarning(result, _t("Receipt Printer"));
        }
        return result;
    },

    async printReturnReceipt(returnId) {
        const receipt = await this.data.call(
            "cb.pos.return",
            "pos_get_return_receipt_data",
            [[returnId]]
        );
        if (!receipt) {
            return;
        }
        const result = await this.printer.print(
            ReturnReceipt,
            { receipt },
            this.printOptions
        );
        if (result?.warningCode) {
            this.displayPrinterWarning(result, _t("Receipt Printer"));
        }
        return result;
    },

    async printExchangeReceipt(exchangeId) {
        const action = await this.data.call(
            "cb.pos.exchange",
            "action_print_exchange_receipt",
            [[exchangeId]]
        );
        if (action) {
            await this.action.doAction(action);
        }
    },

    async openHistoryPopup({ orderId, orderLineId, partnerId } = {}) {
        await makeAwaitable(this.dialog, HistoryPopup, {
            pos: this,
            orderId,
            orderLineId,
            partnerId,
        });
    },

    setLastReturn(returnId) {
        this._cbLastReturnId = returnId;
    },

    getLastReturnId() {
        return this._cbLastReturnId;
    },

    setPendingExchange(pending) {
        this._cbPendingExchange = Boolean(pending);
    },

    clearPendingExchange() {
        this._cbPendingExchange = false;
        this._cbLastReturnId = false;
    },

    getOrderVoucherRedemption(order) {
        const vouchers = this.voucherPayment.getVouchers(order);
        return vouchers[0] || order?.cbReturnVoucher || null;
    },

    getOrderVouchers(order) {
        return this.voucherPayment.getVouchers(order);
    },

    setOrderVoucherRedemption(order, data) {
        if (!order) {
            return;
        }
        order.cbReturnVoucher = data;
        if (data && !this.voucherPayment.hasVoucher(order, data.voucher_id, data.barcode)) {
            order.cbReturnVouchers = order.cbReturnVouchers || [];
            order.cbReturnVouchers.push({
                uuid: crypto.randomUUID(),
                ...data,
                payment_line_uuid: data.payment_line_uuid,
            });
        }
    },

    async applyVoucherFromPaymentScan(barcode, { promptPartial = false } = {}) {
        const order = this.getOrder();
        if (!order) {
            return { success: false, error: _t("No active order.") };
        }
        const settings = await this.returnApi.getSettings();
        if (!this.returnBarcode.guardPermission(settings, "redeem_voucher")) {
            return { success: false, error: _t("Permission denied.") };
        }
        const result = await this.voucherPayment.applyFromBarcode(order, barcode, {
            promptPartial,
        });
        if (result?.success) {
            const partner = order.getPartner?.();
            if (partner?.id) {
                this.voucherPayment.clearCustomerBalanceCache(partner.id);
            }
            this.notification.add(
                _t("Voucher %(name)s applied: %(amount)s", {
                    name: result.entry.name,
                    amount: this.returnApi.formatMoney(result.amount),
                }),
                { type: "success" }
            );
        } else if (result?.error && !result?.cancelled) {
            this.notification.add(result.error, { type: "danger" });
        }
        return result;
    },

    async applyPendingVoucherRedemption(order) {
        if (!order || !this.voucherPayment) {
            return true;
        }
        const orderId = this._getPosOrderServerId(order);
        if (!orderId) {
            // Odoo 19 local orders use a UUID until sync_from_ui assigns a
            // numeric database id — redemption must wait until then.
            return true;
        }
        const vouchers = this.voucherPayment.getVouchers(order);
        if (!vouchers.length) {
            const legacy = order?.cbReturnVoucher;
            if (legacy && !legacy.redeemed) {
                vouchers.push(legacy);
            }
        }
        if (!vouchers.length) {
            return true;
        }
        for (const entry of vouchers) {
            if (entry.redeemed) {
                continue;
            }
            const result = await this.returnApi.redeemVoucher(
                entry.barcode,
                entry.amount,
                orderId,
                entry.issue_remainder || entry.issueRemainder || false
            );
            if (result?.success) {
                entry.redeemed = true;
                const voucher = result.voucher || {};
                entry.voucher_remaining = voucher.amount_remaining ?? entry.voucher_remaining;
            } else if (result?.error) {
                this.notification.add(result.error, { type: "danger" });
                return false;
            }
        }
        if (vouchers.some((v) => v.redeemed)) {
            const partner = order.getPartner?.();
            if (partner?.id) {
                this.voucherPayment.clearCustomerBalanceCache(partner.id);
            }
        }
        return true;
    },

    _getPosOrderServerId(order) {
        if (!order?.isSynced) {
            return null;
        }
        const rawId = order.id;
        if (typeof rawId === "number" && rawId > 0) {
            return rawId;
        }
        if (typeof rawId === "string" && /^\d+$/.test(rawId)) {
            return parseInt(rawId, 10);
        }
        return null;
    },

    async postSyncAllOrders(orders) {
        const current = this.getOrder();
        if (!current?.isSynced || !orders?.length) {
            return;
        }
        const syncedCurrent = orders.some(
            (order) => order.id === current.id || order.uuid === current.uuid
        );
        if (!syncedCurrent) {
            return;
        }
        const redeemed = await this.applyPendingVoucherRedemption(current);
        if (redeemed === false) {
            this.notification.add(
                _t("Voucher redemption failed. Please contact a manager."),
                { type: "danger" }
            );
        }
    },
});
