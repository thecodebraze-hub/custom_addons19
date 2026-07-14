/** @odoo-module **/

import { Component } from "@odoo/owl";

export class VoucherReceipt extends Component {
    static template = "cb_pos_return_exchange.VoucherReceipt";
    static props = {
        receipt: Object,
    };
}
