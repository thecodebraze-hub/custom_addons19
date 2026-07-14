/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useState, useEffect } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { getOnNotified } from "@point_of_sale/utils";
import { CustomerDisplay } from "@point_of_sale/customer_display/customer_display";

patch(CustomerDisplay.prototype, {
    setup() {
        super.setup(...arguments);
        this.cbPartnerSearch = useState({
            query: "",
            results: [],
            selectedName: "",
            loading: false,
            error: "",
            loyaltyPoints: null,
            loyaltyLabel: "",
        });
        this.cbBus = useService("bus_service");
        getOnNotified(this.cbBus, session.access_token)("CB_DISPLAY_PARTNER_STATE", (payload) =>
            this._cbOnPartnerState(payload)
        );
        this._cbOrderWasActive = false;
        useEffect(
            () => {
                const finalized = !!this.order.finalized;
                const lineCount = (this.order.lines || []).length;
                if (lineCount > 0 || finalized) {
                    this._cbOrderWasActive = true;
                } else if (this._cbOrderWasActive) {
                    this._cbOrderWasActive = false;
                    this._cbClearLocal();
                }
            },
            () => [this.order.finalized, (this.order.lines || []).length]
        );
    },

    _cbOnPartnerState(payload) {
        if (payload?.partner_id) {
            this.cbPartnerSearch.selectedName = payload.partner_name || "";
            this.cbPartnerSearch.query = "";
            this.cbPartnerSearch.results = [];
            this.cbPartnerSearch.error = "";
            const points = payload.loyalty_points;
            this.cbPartnerSearch.loyaltyPoints =
                points === undefined || points === null ? null : points;
            this.cbPartnerSearch.loyaltyLabel = payload.loyalty_points_label || "";
        } else {
            this._cbClearLocal();
        }
    },

    _cbClearLocal() {
        this.cbPartnerSearch.selectedName = "";
        this.cbPartnerSearch.query = "";
        this.cbPartnerSearch.results = [];
        this.cbPartnerSearch.error = "";
        this.cbPartnerSearch.loyaltyPoints = null;
        this.cbPartnerSearch.loyaltyLabel = "";
    },

    get cbLoyaltyPointsText() {
        const points = this.cbPartnerSearch.loyaltyPoints;
        if (points === null || points === undefined) {
            return "";
        }
        const rounded = Math.round(points * 100) / 100;
        return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
    },

    async cbSearchPartner() {
        const term = (this.cbPartnerSearch.query || "").trim();
        this.cbPartnerSearch.error = "";
        this.cbPartnerSearch.results = [];
        if (term.length < 3) {
            this.cbPartnerSearch.error = _t("Enter at least 3 characters.");
            return;
        }
        this.cbPartnerSearch.loading = true;
        try {
            const result = await rpc("/cb_pos_customer_display/search", {
                config_id: this.session.config_id,
                access_token: this.session.access_token,
                query: term,
            });
            if (!result?.success) {
                this.cbPartnerSearch.error = result?.error || _t("Search failed.");
                return;
            }
            const partners = result.partners || [];
            this.cbPartnerSearch.results = [];
            if (!partners.length) {
                this.cbPartnerSearch.error = _t("No matching customer found.");
                return;
            }
            if (partners.length > 1) {
                this.cbPartnerSearch.error = _t(
                    "Multiple customers found for this number. Please contact the cashier."
                );
                return;
            }
            await this.cbSelectPartner(partners[0]);
        } catch (error) {
            this.cbPartnerSearch.error =
                error?.data?.message || error?.message || _t("Search failed.");
        } finally {
            this.cbPartnerSearch.loading = false;
        }
    },

    async cbSelectPartner(partner) {
        if (!partner?.id) {
            return;
        }
        this.cbPartnerSearch.loading = true;
        this.cbPartnerSearch.error = "";
        try {
            const result = await rpc("/cb_pos_customer_display/set_partner", {
                config_id: this.session.config_id,
                access_token: this.session.access_token,
                partner_id: partner.id,
            });
            if (result?.success) {
                this.cbPartnerSearch.selectedName = result.partner_name || partner.name;
                this.cbPartnerSearch.results = [];
                this.cbPartnerSearch.query = "";
            } else {
                this.cbPartnerSearch.error = _t("Unable to select customer.");
            }
        } catch (error) {
            this.cbPartnerSearch.error =
                error?.data?.message || error?.message || _t("Unable to select customer.");
        } finally {
            this.cbPartnerSearch.loading = false;
        }
    },

    cbOnSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.cbSearchPartner();
        }
    },

    cbNumpadPress(digit) {
        this.cbPartnerSearch.error = "";
        this.cbPartnerSearch.query = (this.cbPartnerSearch.query || "") + String(digit);
    },

    cbNumpadBackspace() {
        this.cbPartnerSearch.error = "";
        this.cbPartnerSearch.query = (this.cbPartnerSearch.query || "").slice(0, -1);
    },

    cbNumpadClear() {
        this.cbPartnerSearch.error = "";
        this.cbPartnerSearch.query = "";
        this.cbPartnerSearch.results = [];
    },
});
