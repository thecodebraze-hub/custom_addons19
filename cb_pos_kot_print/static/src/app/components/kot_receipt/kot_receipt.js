import { Component } from "@odoo/owl";

export class KotReceiptDisplay extends Component {
    static template = "cb_pos_kot_print.KotReceiptDisplay";
    static props = {
        receiptsData: { type: Array },
    };
}
