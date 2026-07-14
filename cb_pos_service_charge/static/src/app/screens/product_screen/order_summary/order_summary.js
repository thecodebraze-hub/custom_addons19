import { patch } from "@web/core/utils/patch";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(OrderSummary.prototype, {
    async updateSelectedOrderline({ buffer, key }) {
        const selectedLine = this.currentOrder.getSelectedOrderline();
        if (selectedLine?.isServiceChargeLine?.() && this.pos.numpadMode !== "price") {
            this.numberBuffer.reset();
            if (key === "Backspace") {
                this._setValue("remove");
            } else {
                this.dialog.add(AlertDialog, {
                    title: _t("Cannot modify service charge"),
                    body: _t(
                        "Service charge cannot be modified directly. Use Actions → Service Charge."
                    ),
                });
            }
            return;
        }
        return super.updateSelectedOrderline(...arguments);
    },
});
