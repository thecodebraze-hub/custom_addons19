/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { PriceFormatter } from "@point_of_sale/app/components/price_formatter/price_formatter";

export class PaymentVouchersPanel extends Component {
    static template = "cb_pos_return_exchange.PaymentVouchersPanel";
    static components = { PriceFormatter };
    static props = {
        order: { type: Object },
        customerBalance: { type: Number },
        vouchers: { type: Array },
        onRemove: { type: Function },
        formatMoney: { type: Function },
    };

    get hasVouchers() {
        return (this.props.vouchers || []).length > 0;
    }

    format(amount) {
        return this.props.formatMoney(amount || 0);
    }

    totalApplied() {
        return (this.props.vouchers || []).reduce(
            (sum, v) => sum + (Number(v.amount) || 0),
            0
        );
    }

    removeVoucher(entry) {
        this.props.onRemove(entry.uuid);
    }
}
