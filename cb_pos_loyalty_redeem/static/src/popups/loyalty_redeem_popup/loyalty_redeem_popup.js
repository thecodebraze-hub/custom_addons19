/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

export class CbLoyaltyRedeemPopup extends Component {
    static template = "cb_pos_loyalty_redeem.LoyaltyRedeemPopup";
    static components = { Dialog };
    static props = {
        partner: { type: Object },
        balance: { type: Object },
        order: { type: Object },
        maxAmount: { type: Number },
        pointRate: { type: Number },
        minPoints: { type: Number },
        getPayload: { type: Function, optional: true },
        close: { type: Function },
    };

    setup() {
        this.pos = usePos();
        this.state = useState({
            points: "",
            error: "",
        });
    }

    get availablePoints() {
        return this.props.balance.points || 0;
    }

    get pointLabel() {
        return this.props.balance.label || _t("Points");
    }

    get redeemAmount() {
        const points = this._parsedPoints();
        if (!points) {
            return 0;
        }
        const rate = this.props.pointRate || 1;
        return this.pos.env.utils.roundCurrency(points * rate);
    }

    get maxRedeemablePoints() {
        const rate = this.props.pointRate || 1;
        if (!rate) {
            return 0;
        }
        const byBalance = this.availablePoints;
        const byOrder = Math.floor(this.props.maxAmount / rate);
        return Math.max(0, Math.min(byBalance, byOrder));
    }

    _parsedPoints() {
        const value = parseFloat((this.state.points || "").trim());
        return Number.isFinite(value) ? value : 0;
    }

    setMaxPoints() {
        this.state.error = "";
        this.state.points = String(this.maxRedeemablePoints);
    }

    onPointsInput() {
        this.state.error = "";
    }

    confirm() {
        const points = this._parsedPoints();
        const minPoints = this.props.minPoints || 0;
        if (!points || points <= 0) {
            this.state.error = _t("Enter the number of points to redeem.");
            return;
        }
        if (minPoints && points < minPoints) {
            this.state.error = _t("Minimum redemption is %(min)s points.", { min: minPoints });
            return;
        }
        if (points > this.availablePoints + 0.0001) {
            this.state.error = _t("Not enough points. Available: %(pts)s.", {
                pts: this.availablePoints,
            });
            return;
        }
        const amount = this.redeemAmount;
        if (amount <= 0) {
            this.state.error = _t("Redemption amount must be greater than zero.");
            return;
        }
        if (amount > this.props.maxAmount + 0.0001) {
            this.state.error = _t("Redemption cannot exceed the order total.");
            return;
        }
        this.props.getPayload?.({
            confirmed: true,
            points,
            amount,
        });
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
