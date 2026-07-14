/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { CbLoyaltyRedeemPopup } from "../popups/loyalty_redeem_popup/loyalty_redeem_popup";

patch(PosStore.prototype, {
    /**
     * Local (cached) balance, used for the quick label on the button.
     * May be 0 if the card is not loaded yet; the popup uses the server value.
     */
    getPartnerLoyaltyBalance(partner) {
        if (!partner || !this.config.cb_loyalty_redeem_enabled) {
            return { points: 0, label: "", card: null };
        }
        const programId = this.config.cb_loyalty_program_id?.id;
        let cards = this.getLoyaltyCards(partner).filter(
            (card) => card.program_id?.program_type === "loyalty"
        );
        if (programId) {
            cards = cards.filter((card) => card.program_id?.id === programId);
        }
        if (!cards.length) {
            return { points: 0, label: _t("Points"), card: null };
        }
        const points = cards.reduce((sum, card) => sum + (card.points || 0), 0);
        const card = [...cards].sort((a, b) => (b.points || 0) - (a.points || 0))[0];
        const label = card.program_id?.portal_point_name || _t("Points");
        return { points, label, card };
    },

    async cbOpenLoyaltyRedeemPopup() {
        const order = this.getOrder();
        const partner = order?.getPartner();
        if (!partner) {
            this.notification.add(_t("Select a customer first."), { type: "warning" });
            return;
        }
        if (!this.config.cb_loyalty_redeem_enabled) {
            return;
        }
        // Always read the real balance from the server so it is never stale/0.
        let serverBalance;
        try {
            serverBalance = await this.data.call(
                "pos.config",
                "cb_get_partner_loyalty_balance",
                [[this.config.id], partner.id]
            );
        } catch (error) {
            this.notification.add(
                error?.data?.message || error?.message || _t("Could not read loyalty points."),
                { type: "danger" }
            );
            return;
        }
        if (!serverBalance?.card_id || serverBalance.points <= 0) {
            this.notification.add(
                serverBalance?.error
                    || _t("This customer has no redeemable loyalty points."),
                { type: "warning" }
            );
            return;
        }
        const balance = {
            points: serverBalance.points,
            label: serverBalance.label,
            cardId: serverBalance.card_id,
        };
        const result = await makeAwaitable(this.dialog, CbLoyaltyRedeemPopup, {
            partner,
            balance,
            order,
            maxAmount: order.getLoyaltyRedeemBaseTotal(),
            pointRate: this.config.cb_loyalty_point_rate || 1,
            minPoints: this.config.cb_loyalty_min_points || 0,
        });
        if (!result?.confirmed) {
            return;
        }
        await this._cbApplyLoyaltyRedemption(order, result, balance.cardId);
    },

    async _cbApplyLoyaltyRedemption(order, result, cardId) {
        const product = order._getLoyaltyRedeemProduct();
        if (!product) {
            this.notification.add(_t("Loyalty redemption product is not configured."), {
                type: "danger",
            });
            return;
        }
        order.clearLoyaltyRedemption();
        const amount = this.env.utils.roundCurrency(-Math.abs(result.amount));
        await this.addLineToCurrentOrder(
            {
                product_id: product,
                product_tmpl_id: product.product_tmpl_id,
            },
            {
                price_unit: amount,
                merge: false,
            }
        );
        order.cb_loyalty_redeem_points = result.points;
        order.cb_loyalty_redeem_amount = Math.abs(result.amount);
        order.cb_loyalty_redeem_card_id = cardId;
        order.cb_loyalty_redeem_applied = false;
        this.notification.add(
            _t("Redeemed %(points)s points ( %(amount)s ).", {
                points: result.points,
                amount: this.env.utils.formatCurrency(Math.abs(result.amount)),
            }),
            { type: "success" }
        );
    },

    async selectPartner(partner) {
        const order = this.getOrder();
        if (order?.getLoyaltyRedeemLine()) {
            order.clearLoyaltyRedemption();
        }
        return super.selectPartner(...arguments);
    },

    async postSyncAllOrders(orders) {
        await super.postSyncAllOrders(...arguments);
        for (const order of orders) {
            if (
                order.cb_loyalty_redeem_points &&
                order.cb_loyalty_redeem_card_id &&
                !order.cb_loyalty_redeem_applied &&
                order.state !== "draft" &&
                order.state !== "cancel"
            ) {
                const card = this.models["loyalty.card"].get(order.cb_loyalty_redeem_card_id);
                if (card) {
                    card.points = Math.max(
                        0,
                        (card.points || 0) - order.cb_loyalty_redeem_points
                    );
                }
                order.cb_loyalty_redeem_applied = true;
            }
        }
    },
});
