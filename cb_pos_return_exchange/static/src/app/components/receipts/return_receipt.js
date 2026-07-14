/** @odoo-module **/

import { Component } from "@odoo/owl";

export class ReturnReceipt extends Component {
    static template = "cb_pos_return_exchange.ReturnReceipt";
    static props = {
        receipt: Object,
    };
}
