/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import { formatDateTime, deserializeDateTime } from "@web/core/l10n/dates";

export class ReturnPopup extends Component {
    static template = "cb_pos_return_exchange.ReturnPopup";
    static components = { Dialog };
    static props = {
        pos: { type: Object },
        exchangeMode: { type: Boolean, optional: true },
        getPayload: { type: Function },
        close: { type: Function },
    };

    get isExchangeMode() {
        return Boolean(this.props.exchangeMode);
    }

    get popupTitle() {
        return _t("Return / Exchange");
    }

    get modeHint() {
        return _t(
            "Scan a receipt / order to return it, or a product to issue an exchange voucher."
        );
    }

    get searchPlaceholder() {
        return _t("Receipt number or product barcode");
    }

    get searchIcon() {
        return "fa-search";
    }

    setup() {
        this.api = this.props.pos.returnApi;
        this.barcodeHandler = this.props.pos.returnBarcode;
        this.inputRef = useRef("searchInput");
        this.state = useState({
            mode: "auto",
            search: "",
            loading: false,
            error: "",
            results: [],
            giftCart: [],
            giftBusy: false,
        });
        this._pendingProduct = null;

        useBarcodeReader(this.barcodeHandler.buildCallbackMap(this), true);

        onMounted(() => {
            this.barcodeHandler.setMode("auto");
            this.unregisterBarcode = this.barcodeHandler.setExclusive((code) =>
                this.onBarcodeScanned(code)
            );
            this.inputRef.el?.focus();
        });

        onWillUnmount(() => {
            this.unregisterBarcode?.();
        });
    }

    async onBarcodeScanned(code) {
        this.state.search = code;
        await this.search();
    }

    async onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            await this.search();
        }
    }

    async search() {
        this.state.error = "";
        const term = (this.state.search || "").trim();
        if (!term) {
            this.state.error = _t("Scan or type a receipt or product barcode.");
            return;
        }
        this.state.loading = true;
        try {
            // 1) Voucher / return-document barcode → hand off to the global
            //    router (which runs after this popup closes).
            const classification = await this.barcodeHandler.classify(term);
            const type = classification?.success ? classification.barcode_type : null;
            if (type === "voucher" || type === "return") {
                this.props.getPayload({ action: "barcode", code: term });
                this.props.close();
                return;
            }

            // 2) Receipt / order reference → list matching orders so the
            //    cashier can pick one and do a normal (original-order) return.
            const orderResult = await this.api.findOrder(term);
            if (orderResult?.success) {
                const orders =
                    orderResult.orders || (orderResult.order ? [orderResult.order] : []);
                if (orders.length) {
                    this.state.giftCart = [];
                    this._pendingProduct = null;
                    this.state.results = orders;
                    return;
                }
            }

            // 3) Otherwise the scan is treated as a product barcode. No orders
            //    are shown — the product's details are added directly and, once
            //    confirmed, an exchange voucher barcode is generated.
            this.state.results = [];
            await this.addGiftProduct(term);
        } finally {
            this.state.loading = false;
        }
    }

    selectOrder(order) {
        this.props.getPayload({
            action: "order_found",
            order,
            product: this._pendingProduct || null,
        });
        this.props.close();
    }

    // ---- Product-scan exchange (no order shown) ---------------------------

    get giftTotal() {
        return this.state.giftCart.reduce((sum, item) => sum + (item.amount || 0), 0);
    }

    async addGiftProduct(term) {
        const code = (term || "").trim();
        if (!code) {
            this.state.error = _t("Scan a product barcode.");
            return;
        }
        const result = await this.api.getProductReturnValue({ barcode: code });
        if (!result?.success) {
            this.state.error = _t(
                "No matching receipt, order, or product found for \u201C%s\u201D.",
                code
            );
            return;
        }
        const product = result.product;
        const unitValue = Number(result.unit_value) || 0;
        const existing = this.state.giftCart.find((i) => i.product_id === product.id);
        if (existing) {
            existing.qty += 1;
            existing.amount = existing.qty * existing.unit_value;
        } else {
            this.state.giftCart.push({
                product_id: product.id,
                product_name: product.name,
                barcode: product.barcode || code,
                qty: 1,
                unit_value: unitValue,
                amount: unitValue,
            });
        }
        this.state.search = "";
        this.inputRef.el?.focus();
    }

    changeGiftQty(item, ev) {
        let qty = Number(ev.target.value) || 0;
        qty = Math.max(qty, 0);
        item.qty = qty;
        item.amount = qty * item.unit_value;
        if (qty <= 0) {
            this.removeGiftItem(item);
        }
    }

    removeGiftItem(item) {
        const idx = this.state.giftCart.indexOf(item);
        if (idx >= 0) {
            this.state.giftCart.splice(idx, 1);
        }
    }

    async issueGiftVoucher() {
        if (!this.state.giftCart.length || this.state.giftBusy) {
            return;
        }
        this.state.giftBusy = true;
        this.state.error = "";
        try {
            const payload = {
                client_uuid: crypto.randomUUID(),
                partner_id: this.props.pos.getOrder()?.getPartner?.()?.id || false,
                lines: this.state.giftCart.map((item) => ({
                    product_id: item.product_id,
                    barcode: item.barcode,
                    qty: item.qty,
                })),
            };
            const result = await this.api.createGiftVoucher(payload);
            if (!result?.success) {
                this.state.error = result?.error || _t("Unable to issue voucher.");
                return;
            }
            this.props.getPayload({
                action: "gift_voucher",
                voucher: result.voucher,
                amount: result.amount,
            });
            this.props.close();
        } finally {
            this.state.giftBusy = false;
        }
    }

    orderDisplayRef(order) {
        return order.pos_reference || order.name || `#${order.id}`;
    }

    orderDisplayDate(order) {
        if (!order.date_order) {
            return "";
        }
        try {
            return formatDateTime(deserializeDateTime(order.date_order), { format: "short" });
        } catch {
            return order.date_order;
        }
    }

    orderMoney(amount) {
        return this.api.formatMoney(amount);
    }

    cancel() {
        this.props.close();
    }
}
