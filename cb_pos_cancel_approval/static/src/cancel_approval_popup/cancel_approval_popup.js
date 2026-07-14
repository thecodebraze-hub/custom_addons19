/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

export class CbCancelApprovalPopup extends Component {
    static template = "cb_pos_cancel_approval.CancelApprovalPopup";
    static components = { Dialog };
    static props = {
        actionType: { type: String, optional: true },
        orderReference: { type: String, optional: true },
        productName: { type: String, optional: true },
        amount: { type: Number, optional: true },
        getPayload: { type: Function, optional: true },
        close: { type: Function },
    };

    setup() {
        this.pos = usePos();
        this.state = useState({ pin: "", reason: "", error: "", loading: false });
    }

    get dialogTitle() {
        return this.props.actionType === "remove_line"
            ? _t("Manager Approval to Remove Item")
            : _t("Manager Approval to Cancel Order");
    }

    get dialogMessage() {
        if (this.props.actionType === "remove_line" && this.props.productName) {
            return _t(
                "Manager approval is required to remove %(product)s from this order.",
                { product: this.props.productName }
            );
        }
        return _t("Manager approval is required to cancel this order.");
    }

    get confirmLabel() {
        return this.props.actionType === "remove_line"
            ? _t("Approve & Remove Item")
            : _t("Approve & Cancel Order");
    }

    addDigit(digit) {
        this.state.error = "";
        this.state.pin += String(digit);
    }

    backspace() {
        this.state.error = "";
        this.state.pin = this.state.pin.slice(0, -1);
    }

    clearPin() {
        this.state.error = "";
        this.state.pin = "";
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.confirm();
        }
    }

    async confirm() {
        const reason = (this.state.reason || "").trim();
        if (!reason) {
            this.state.error = _t("Enter a reason.");
            return;
        }
        const pin = (this.state.pin || "").trim();
        if (!pin) {
            this.state.error = _t("Enter the manager PIN.");
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        try {
            const result = await this.pos.data.call(
                "pos.config",
                "cb_verify_cancel_manager_pin",
                [[this.pos.config.id], pin]
            );
            if (!result?.success) {
                this.state.error = result?.error || _t("Invalid manager PIN.");
                this.state.pin = "";
                return;
            }
            this.props.getPayload?.({
                approved: true,
                manager_id: result.manager_id,
                manager_name: result.manager_name,
                reason,
            });
            this.props.close();
        } catch (error) {
            this.state.error =
                error?.data?.message || error?.message || _t("Approval failed.");
        } finally {
            this.state.loading = false;
        }
    }

    cancel() {
        this.props.close();
    }
}
