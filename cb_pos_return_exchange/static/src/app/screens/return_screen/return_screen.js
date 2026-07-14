/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import { BackButton } from "@point_of_sale/app/screens/product_screen/action_pad/back_button/back_button";
import "../../load_services";
import { formatDateTime } from "@web/core/l10n/dates";

export class ReturnScreen extends Component {
    static storeOnOrder = false;
    static template = "cb_pos_return_exchange.ReturnScreen";
    static components = { BackButton };
    static props = {
        searchTerm: { type: String, optional: true },
        orderId: { type: Number, optional: true },
        order: { type: Object, optional: true },
        exchangeMode: { type: Boolean, optional: true },
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.api = this.pos.returnApi;
        this.barcodeHandler = this.pos.returnBarcode;
        this.searchRef = useRef("searchInput");
        this._recalculateToken = 0;

        this.state = useState({
            search: this.props.searchTerm || "",
            loading: false,
            error: "",
            order: this.props.order || null,
            lines: [],
            refundMethod: "exchange",
            hasReceipt: true,
            reason: "",
            note: "",
            approvalRequired: false,
            approvalReasons: [],
            amountTotal: 0,
            settings: null,
            clientUuid: crypto.randomUUID(),
        });

        useBarcodeReader(this.barcodeHandler.buildCallbackMap(this), true);

        onMounted(async () => {
            this.barcodeHandler.setMode("auto");
            this.unregisterBarcode = this.barcodeHandler.setExclusive((code) =>
                this.onBarcodeScanned(code)
            );
            const settingsResult = await this.api.getSettings();
            this.state.settings = settingsResult?.settings || {};
            if (this.props.order) {
                this.loadOrder(this.props.order);
            } else if (this.props.orderId) {
                await this.findOrder(String(this.props.orderId));
            } else if (this.state.search) {
                await this.findOrder(this.state.search);
            } else {
                this.searchRef.el?.focus();
            }
        });

        onWillUnmount(() => {
            this.unregisterBarcode?.();
            this.barcodeHandler.setMode("auto");
        });
    }

    get isExchangeMode() {
        return Boolean(this.props.exchangeMode);
    }

    get isExchangeSettlement() {
        return this.isExchangeMode || this.state.refundMethod === "exchange";
    }

    get screenTitle() {
        return _t("Return / Exchange");
    }

    get confirmLabel() {
        return _t("Confirm Return");
    }

    formatMoney(amount) {
        return this.api.formatMoney(amount);
    }

    formatDate(value) {
        if (!value) {
            return "—";
        }
        try {
            return formatDateTime(value, { format: "short" });
        } catch {
            return value;
        }
    }

    get selectedLines() {
        return this.state.lines.filter((l) => l.selected);
    }

    get hasTrackedLines() {
        return this.state.lines.some((line) => line.tracking !== "none");
    }

    get canConfirm() {
        return (
            this.selectedLines.length > 0 &&
            !this.state.loading &&
            !this.state.error &&
            (!this.state.approvalRequired || this.pos.cashier?._role === "manager")
        );
    }

    loadOrder(order) {
        this.state.order = order;
        this.state.lines = (order.lines || []).map((line) => ({
            selected: false,
            order_line_id: line.id,
            product_id: line.product_id,
            product_name: line.product_name,
            qty_returnable: line.qty_returnable,
            qty: line.qty_returnable,
            price_unit: line.price_unit,
            discount: line.discount || 0,
            tracking: line.tracking,
            lot_names: line.lot_names || [],
            lot_name:
                line.lot_names && line.lot_names.length === 1 ? line.lot_names[0] : "",
            lot_id: false,
            disposition: "restock",
            amount_total: 0,
        }));
        this.state.error = "";
    }

    async onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            await this.findOrder();
        }
    }

    async onBarcodeScanned(code) {
        // When an order is already loaded, a scanned product barcode should
        // auto-select the matching return line instead of searching for a new
        // order. Only fall back to order lookup when the scan is not a product
        // that belongs to the current order (e.g. a receipt / order reference).
        if (this.state.order && this.selectLineByBarcode(code)) {
            return;
        }
        this.state.search = code;
        await this.findOrder(code);
    }

    selectLineByBarcode(code) {
        const product = this.api.findLocalProduct(code);
        if (!product) {
            return false;
        }
        const matches = this.state.lines.filter((l) => l.product_id === product.id);
        if (!matches.length) {
            this.notification.add(
                _t("%s is not part of this order.", product.display_name || code),
                { type: "warning" }
            );
            return true;
        }
        const returnable = matches.filter((l) => l.qty_returnable > 0);
        if (!returnable.length) {
            this.notification.add(
                _t("%s is already fully returned.", product.display_name || code),
                { type: "warning" }
            );
            return true;
        }
        for (const line of returnable) {
            line.selected = true;
            if (!line.qty) {
                line.qty = line.qty_returnable;
            }
        }
        this.recalculate();
        this.notification.add(
            _t("%s selected for return.", product.display_name || code),
            { type: "success" }
        );
        return true;
    }

    async findOrder(term) {
        const searchTerm = (term || this.state.search || "").trim();
        if (!searchTerm) {
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        try {
            const result = await this.api.findOrder(searchTerm);
            if (!result?.success) {
                this.state.error = result?.error || _t("Order not found.");
                this.state.order = null;
                this.state.lines = [];
                return;
            }
            this.loadOrder(result.order);
        } finally {
            this.state.loading = false;
        }
    }

    toggleLine(line) {
        if (line.qty_returnable <= 0) {
            return;
        }
        line.selected = !line.selected;
        if (line.selected && !line.qty) {
            line.qty = line.qty_returnable;
        }
        this.recalculate();
    }

    onQtyChange(line, ev) {
        if (line.qty_returnable <= 0) {
            return;
        }
        let qty = Number(ev.target.value) || 0;
        qty = Math.min(Math.max(qty, 0), line.qty_returnable);
        line.qty = qty;
        line.selected = qty > 0;
        this.recalculate();
    }

    get hasReturnableLines() {
        return this.state.lines.some((line) => line.qty_returnable > 0);
    }

    async recalculate() {
        if (!this.state.order || !this.selectedLines.length) {
            this.state.amountTotal = 0;
            this.state.approvalRequired = false;
            return;
        }
        const token = ++this._recalculateToken;
        await new Promise((resolve) => setTimeout(resolve, 250));
        if (token !== this._recalculateToken) {
            return;
        }
        const payload = this.buildPayload();
        const result = await this.api.validateReturn(payload);
        if (token !== this._recalculateToken) {
            return;
        }
        if (!result?.success) {
            this.state.error = result?.error || _t("Validation failed.");
            return;
        }
        this.state.error = "";
        this.state.approvalRequired = result.approval_required;
        this.state.approvalReasons = result.approval_reasons || [];
        this.state.amountTotal = result.amount_total || 0;
        for (const vline of result.lines || []) {
            const local = this.state.lines.find((l) => l.order_line_id === vline.order_line_id);
            if (local) {
                local.amount_total = vline.amount_total;
            }
        }
    }

    buildPayload() {
        return {
            order_id: this.state.order.id,
            refund_method: this.state.refundMethod,
            has_receipt: this.state.hasReceipt,
            reason: this.state.reason,
            note: this.state.note,
            client_uuid: this.state.clientUuid,
            lines: this.selectedLines.map((line) => ({
                order_line_id: line.order_line_id,
                qty: line.qty,
                lot_id: line.lot_id || false,
                lot_name: line.lot_name || false,
                disposition: line.disposition,
            })),
        };
    }

    async showHistory() {
        if (!this.state.order) {
            return;
        }
        await this.pos.openHistoryPopup({ orderId: this.state.order.id });
    }

    async confirmReturn() {
        if (!this.canConfirm) {
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        try {
            const payload = this.buildPayload();
            const validation = await this.api.validateReturn(payload);
            if (!validation?.success || !validation.valid) {
                this.state.error = validation?.error || _t("Validation failed.");
                return;
            }
            const result = await this.api.confirmReturn(payload);
            if (!result?.success) {
                this.state.error = result?.error || _t("Return failed.");
                return;
            }
            if (result.duplicate) {
                this.notification.add(
                    _t("Return already processed (%s).", result.return_name),
                    { type: "warning" }
                );
            } else {
                this.notification.add(
                    _t("Return %(name)s completed.", { name: result.return_name }),
                    { type: "success" }
                );
            }
            this.pos.setLastReturn(result.return_id);
            // Always print a barcode receipt on confirm, regardless of the
            // chosen settlement method.
            if (result.return_id) {
                await this.pos.printReturnReceipt(result.return_id);
            }
            if (result.voucher) {
                await this.pos.showVoucherPopup(result.voucher, result);
            }
            // The return barcode receipt is printed above. The customer now bills
            // replacement products normally and redeems the printed voucher at the
            // payment screen (Scan Voucher), so no full-screen exchange handoff.
            this.back();
        } finally {
            this.state.loading = false;
        }
    }

    back() {
        this.pos.navigate("ProductScreen", { orderUuid: this.pos.getOrder()?.uuid });
    }
}

registry.category("pos_pages").add("CbReturnScreen", {
    name: "CbReturnScreen",
    component: ReturnScreen,
    route: `/pos/ui/${odoo.pos_config_id}/return`,
    params: {},
});
