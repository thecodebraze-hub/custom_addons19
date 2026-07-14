/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { _t } from "@web/core/l10n/translation";

patch(PosStore.prototype, {
    async setup(...args) {
        await super.setup(...args);
        this.data.connectWebSocket("CB_DISPLAY_SET_PARTNER", (payload) =>
            this._cbApplyDisplayPartner(payload)
        );
    },

    setPartnerToCurrentOrder(partner) {
        if (partner) {
            super.setPartnerToCurrentOrder(partner);
        } else {
            const order = this.getOrder();
            if (order) {
                order.partner_id = false;
                order.updatePricelistAndFiscalPosition(false);
            }
        }
        this._cbBroadcastDisplayPartner();
    },

    _cbBroadcastDisplayPartner() {
        const partner = this.getOrder()?.getPartner();
        this.data
            .call("pos.config", "cb_display_broadcast_partner", [
                [this.config.id],
                partner ? partner.id : false,
                partner ? partner.name || partner.display_name : "",
            ])
            .catch(() => {});
    },

    async _cbApplyDisplayPartner(payload) {
        const order = this.getOrder();
        if (!order) {
            return;
        }
        const partnerId = payload?.partner_id;
        if (!partnerId) {
            this.setPartnerToCurrentOrder(false);
            return;
        }
        let partner = this.models["res.partner"]?.get(partnerId);
        if (!partner) {
            try {
                await this.data.callRelated("res.partner", "get_new_partner", [
                    this.config.id,
                    [["id", "=", partnerId]],
                    0,
                ]);
                partner = this.models["res.partner"]?.get(partnerId);
            } catch (error) {
                this.notification.add(
                    error?.data?.message || error?.message || _t("Customer not found."),
                    { type: "danger" }
                );
                return;
            }
        }
        if (!partner) {
            this.notification.add(_t("Customer not found."), { type: "danger" });
            return;
        }
        this.setPartnerToCurrentOrder(partner);
        this.notification.add(
            _t("Customer selected: %(name)s", { name: partner.name || partner.display_name }),
            { type: "success" }
        );
    },
});
