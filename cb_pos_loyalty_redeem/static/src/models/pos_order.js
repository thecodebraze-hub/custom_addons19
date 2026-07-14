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
        const product = this.config.cb_loyalty_redeem_product_id;
        if (!product) {
            return null;
        }
        if (typeof product === "number") {
            return this.models["product.product"].get(product);
        }
        return product;
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
