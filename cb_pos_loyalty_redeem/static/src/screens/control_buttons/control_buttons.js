/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";

patch(ControlButtons.prototype, {
    get cbShowLoyaltyRedeem() {
        return (
            this.pos.config.cb_loyalty_redeem_enabled &&
            this.partner &&
            !this.currentOrder?.finalized
        );
    },

    get cbPartnerLoyaltyText() {
        if (!this.partner) {
            return "";
        }
        const balance = this.pos.getPartnerLoyaltyBalance(this.partner);
        if (!balance.points) {
            return "";
        }
        const rounded =
            Math.round(balance.points * 100) / 100 === Math.floor(balance.points)
                ? String(Math.floor(balance.points))
                : balance.points.toFixed(2);
        return `${rounded} ${balance.label}`;
    },

    async onRedeemLoyaltyPoints() {
        await this.pos.cbOpenLoyaltyRedeemPopup();
        if (this.props.close) {
            this.props.close();
        }
    },
});
