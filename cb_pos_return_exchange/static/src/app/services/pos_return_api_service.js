/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";

const API_MODEL = "cb.pos.return.api";

/**
 * Thin client for cb.pos.return.api backend RPCs.
 */
export class PosReturnApiService {
    constructor(pos) {
        this.pos = pos;
        this._settings = null;
    }

    get configId() {
        return this.pos.config.id;
    }

    get sessionId() {
        return this.pos.session?.id || false;
    }

    get isOffline() {
        const network = this.pos.data?.network?.unsyncData;
        if (network && typeof network.hasConnection === "function") {
            return !network.hasConnection();
        }
        return typeof navigator !== "undefined" ? !navigator.onLine : false;
    }

    formatMoney(amount) {
        return formatCurrency(amount || 0, this.pos.currency);
    }

    async call(method, args = []) {
        if (this.isOffline) {
            return { success: false, error_code: "offline", error: _t("POS is offline.") };
        }
        try {
            return await this.pos.data.call(API_MODEL, method, args);
        } catch (error) {
            const message =
                error?.data?.message ||
                error?.message ||
                _t("Request failed.");
            return {
                success: false,
                error_code: "rpc_error",
                error: message,
            };
        }
    }

    async getSettings(force = false) {
        if (this._settings && !force) {
            return this._settings;
        }
        const result = await this.call("pos_get_settings", [this.configId, this.sessionId]);
        if (result?.success) {
            this._settings = result;
        }
        return result;
    }

    async findOrder(searchTerm) {
        return this.call("pos_find_order", [this.configId, this.sessionId, searchTerm]);
    }

    async findProduct({ barcode, productId, partnerId, limit = 20 } = {}) {
        return this.call("pos_find_product", [
            this.configId,
            this.sessionId,
            barcode || false,
            productId || false,
            partnerId || false,
            limit,
        ]);
    }

    async findOrdersByPhone(phone) {
        return this.call("pos_find_orders_by_phone", [this.configId, this.sessionId, phone]);
    }

    async getProductReturnValue({ barcode, productId } = {}) {
        return this.call("pos_get_product_return_value", [
            this.configId,
            this.sessionId,
            barcode || false,
            productId || false,
        ]);
    }

    async createGiftVoucher(payload) {
        return this.call("pos_create_gift_voucher", [this.configId, this.sessionId, payload]);
    }

    async validateReturn(payload) {
        return this.call("pos_validate_return", [this.configId, this.sessionId, payload]);
    }

    async confirmReturn(payload) {
        return this.call("pos_confirm_return", [this.configId, this.sessionId, payload]);
    }

    async generateVoucher(returnId) {
        return this.call("pos_generate_voucher", [this.configId, this.sessionId, returnId]);
    }

    async validateVoucher(barcode) {
        return this.call("pos_validate_voucher", [this.configId, this.sessionId, barcode]);
    }

    async validateVoucherPayment(barcode, { partnerId = false, appliedVoucherIds = [] } = {}) {
        return this.call("pos_validate_voucher_payment", [
            this.configId,
            this.sessionId,
            barcode,
            partnerId,
            appliedVoucherIds,
        ]);
    }

    async getCustomerVoucherBalance(partnerId) {
        return this.call("pos_get_customer_voucher_balance", [
            this.configId,
            this.sessionId,
            partnerId,
        ]);
    }

    async redeemVoucher(barcode, amount, orderId, issueRemainder = false) {
        return this.call("pos_redeem_voucher", [
            this.configId,
            this.sessionId,
            barcode,
            amount,
            orderId,
            issueRemainder,
        ]);
    }

    async returnHistory({ orderId, orderLineId } = {}) {
        return this.call("pos_return_history", [
            this.configId,
            this.sessionId,
            orderId || false,
            orderLineId || false,
        ]);
    }

    async customerReturns(partnerId, limit = 20) {
        return this.call("pos_customer_returns", [
            this.configId,
            this.sessionId,
            partnerId,
            limit,
        ]);
    }

    async classifyBarcode(barcode) {
        return this.call("pos_classify_barcode", [this.configId, this.sessionId, barcode]);
    }

    async createExchange(payload) {
        if (this.isOffline) {
            return { success: false, error: _t("POS is offline.") };
        }
        try {
            return await this.pos.data.call("cb.pos.exchange", "pos_create_exchange", [
                payload,
                this.configId,
                this.sessionId,
            ]);
        } catch (error) {
            return { success: false, error: error?.message || _t("Exchange failed.") };
        }
    }

    findLocalProduct(barcode) {
        const code = (barcode || "").trim();
        if (!code) {
            return null;
        }
        const Product = this.pos.models["product.product"];
        return (
            Product.getBy?.("barcode", code) ||
            Product.getAll().find(
                (p) =>
                    p.barcode === code ||
                    p.default_code === code ||
                    (code.replace(/^0+/, "") && p.barcode === code.replace(/^0+/, ""))
            ) ||
            null
        );
    }

    findLocalOrderByReference(term) {
        const needle = (term || "").trim().toLowerCase();
        if (!needle) {
            return null;
        }
        return (
            (this.pos.models["pos.order"]?.getAll?.() || []).find((order) => {
                if (!["paid", "done", "invoiced"].includes(order.state) || order.is_refund) {
                    return false;
                }
                const refs = [order.pos_reference, order.name, order.tracking_number]
                    .filter(Boolean)
                    .map((v) => String(v).toLowerCase());
                return refs.some((ref) => ref === needle || ref.includes(needle));
            }) || null
        );
    }
}
