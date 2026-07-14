/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { formatDateTime } from "@web/core/l10n/dates";

export class VoucherPopup extends Component {
    static template = "cb_pos_return_exchange.VoucherPopup";
    static components = { Dialog };
    static props = {
        pos: { type: Object },
        voucher: { type: Object },
        returnDoc: { type: Object, optional: true },
        getPayload: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.api = this.props.pos.returnApi;
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

    confirm() {
        this.props.getPayload({ action: "closed" });
        this.props.close();
    }

    printVoucher() {
        if (this.props.voucher?.id) {
            this.props.pos.printVoucherReceipt(this.props.voucher.id);
        }
        this.confirm();
    }
}
