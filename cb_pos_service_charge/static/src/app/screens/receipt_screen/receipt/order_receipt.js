import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

patch(OrderReceipt.prototype, {
    get hasServiceCharge() {
        const order = this.order;
        if (!order) {
            return false;
        }
        try {
            return Boolean(order.hasServiceCharge);
        } catch {
            return false;
        }
    },

    get serviceChargeLabel() {
        try {
            return this.order?.serviceChargeLabel || "Service Charge";
        } catch {
            return "Service Charge";
        }
    },

    get currencyServiceChargeAmount() {
        try {
            return this.order?.currencyServiceChargeAmount || this.formatCurrency(0);
        } catch {
            return this.formatCurrency(0);
        }
    },
});
