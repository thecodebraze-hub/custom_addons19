import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import {
    Numpad,
    getButtons,
    BACKSPACE,
    DECIMAL,
    ZERO,
    EMPTY,
} from "@point_of_sale/app/components/numpad/numpad";
import {
    formatCurrency,
    roundCurrency,
} from "@point_of_sale/app/models/utils/currency";

export class ServiceChargePopup extends Component {
    static template = "cb_pos_service_charge.ServiceChargePopup";
    static components = { Dialog, Numpad };
    static props = {
        order: { type: Object },
        startingRate: { type: Number, optional: true },
        getPayload: { type: Function },
        close: { type: Function },
    };
    static defaultProps = {
        startingRate: 10,
    };

    setup() {
        this.state = useState({
            rate: String(this.props.startingRate ?? 10),
        });
    }

    get buttons() {
        return getButtons(
            [DECIMAL, ZERO, EMPTY],
            [
                BACKSPACE,
                { value: "+", text: "+" },
                { value: "-", text: "−" },
                { value: "%", text: "%", class: "svc-numpad-percent" },
            ]
        );
    }

    get numericRate() {
        const value = parseFloat(this.state.rate);
        return Number.isFinite(value) ? value : 0;
    }

    get displayRate() {
        return this.state.rate || "0";
    }

    get orderTotal() {
        return this.props.order.getServiceChargeBase();
    }

    get formattedOrderTotal() {
        return formatCurrency(this.orderTotal, this.props.order.currency);
    }

    get previewAmount() {
        return roundCurrency(
            this.orderTotal * (this.numericRate / 100),
            this.props.order.currency
        );
    }

    get formattedPreviewAmount() {
        return formatCurrency(this.previewAmount, this.props.order.currency);
    }

    get formattedFinalTotal() {
        return formatCurrency(this.orderTotal + this.previewAmount, this.props.order.currency);
    }

    get isValid() {
        return this.numericRate >= 0 && this.numericRate <= 100;
    }

    onNumpadClick(buttonValue) {
        if (buttonValue === "Backspace") {
            this.state.rate = this.state.rate.slice(0, -1);
            return;
        }
        if (buttonValue === "+" || buttonValue === "-" || buttonValue === "%") {
            return;
        }
        if (buttonValue === "+/-") {
            return;
        }
        if (this.state.rate === "0" && buttonValue !== ".") {
            this.state.rate = buttonValue;
            return;
        }
        this.state.rate += buttonValue;
    }

    clearServiceCharge() {
        this.props.getPayload({ rate: 0 });
        this.props.close();
    }

    confirm() {
        if (!this.isValid) {
            return;
        }
        this.props.getPayload({ rate: this.numericRate });
        this.props.close();
    }
}
