/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(vals);
        this.cb_loyalty_redeem_points = vals.cb_loyalty_redeem_points || 0;
        this.cb_loyalty_redeem_amount = vals.cb_loyalty_redeem_amount || 0;
        this.cb_loyalty_redeem_card_id = vals.cb_loyalty_redeem_card_id || false;
        this.cb_loyalty_redeem_applied = vals.cb_loyalty_redeem_applied || false;
    },

    getLoyaltyRedeemLine() {
        const product = this._getLoyaltyRedeemProduct();
        if (!product) {
            return null;
        }
        return this.lines.find((line) => line.product_id?.id === product.id) || null;
    },

    _getLoyaltyRedeemProduct() {
        const raw = this.config.cb_loyalty_redeem_product_id;
        const productId = typeof raw === "number" ? raw : raw?.id;
        if (productId) {
            const loaded = this.models["product.product"].get(productId);
            if (loaded) {
                return loaded;
            }
            // Relation may exist on config even if the product record is missing
            // from IndexedDB (session opened before product was set).
            if (raw && typeof raw === "object" && raw.product_tmpl_id) {
                return raw;
            }
        }
        // Fallback: find special "LOYALTY_REDEEM" product loaded for the session.
        const specialIds = this.config._pos_special_products_ids || [];
        for (const id of specialIds) {
            const candidate = this.models["product.product"].get(id);
            if (candidate?.default_code === "LOYALTY_REDEEM") {
                return candidate;
            }
        }
        const all = this.models["product.product"].getAll?.() || [];
        return all.find((p) => p.default_code === "LOYALTY_REDEEM") || null;
    },

    getLoyaltyRedeemBaseTotal() {
        const redeemLine = this.getLoyaltyRedeemLine();
        let total = this.priceIncl;
        if (redeemLine) {
            total -= redeemLine.prices?.total_included_currency ?? 0;
        }
        return Math.max(0, total);
    },

    clearLoyaltyRedemption() {
        const line = this.getLoyaltyRedeemLine();
        if (line) {
            line.delete();
        }
        this.cb_loyalty_redeem_points = 0;
        this.cb_loyalty_redeem_amount = 0;
        this.cb_loyalty_redeem_card_id = false;
        this.cb_loyalty_redeem_applied = false;
    },
});
