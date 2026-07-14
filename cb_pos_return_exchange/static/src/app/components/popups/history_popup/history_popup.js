/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { formatDateTime } from "@web/core/l10n/dates";

export class HistoryPopup extends Component {
    static template = "cb_pos_return_exchange.HistoryPopup";
    static components = { Dialog };
    static props = {
        pos: { type: Object },
        orderId: { type: Number, optional: true },
        orderLineId: { type: Number, optional: true },
        partnerId: { type: Number, optional: true },
        getPayload: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.api = this.props.pos.returnApi;
        this.state = useState({
            loading: true,
            error: "",
            history: [],
            returns: [],
        });

        onMounted(() => this.load());
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

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            if (this.props.partnerId) {
                const result = await this.api.customerReturns(this.props.partnerId);
                if (!result?.success) {
                    this.state.error = result?.error || _t("Unable to load returns.");
                    return;
                }
                this.state.returns = result.returns || [];
                return;
            }
            const result = await this.api.returnHistory({
                orderId: this.props.orderId,
                orderLineId: this.props.orderLineId,
            });
            if (!result?.success) {
                this.state.error = result?.error || _t("Unable to load history.");
                return;
            }
            this.state.history = result.history || [];
        } finally {
            this.state.loading = false;
        }
    }

    close() {
        this.props.close();
    }
}
