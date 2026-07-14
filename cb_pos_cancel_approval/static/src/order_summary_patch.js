/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";

patch(OrderSummary.prototype, {
    async _setValue(val) {
        if (
            val === "remove" &&
            this.pos.config.cb_require_cancel_approval &&
            this.pos.numpadMode === "quantity"
        ) {
            let selectedLine = this.currentOrder.getSelectedOrderline();
            if (selectedLine?.combo_parent_id) {
                selectedLine = selectedLine.combo_parent_id;
            }
            if (selectedLine) {
                const approved = await this.pos.cbRequestCancelApproval({
                    actionType: "remove_line",
                    orderReference: this.currentOrder.pos_reference,
                    productName: selectedLine.getFullProductName(),
                    amount: selectedLine.prices?.total_included_currency ?? 0,
                });
                if (!approved) {
                    this.numberBuffer?.reset();
                    return;
                }
            }
        }
        return super._setValue(...arguments);
    },
});
