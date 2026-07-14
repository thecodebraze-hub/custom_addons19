/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

patch(OrderReceipt.prototype, {
    /**
     * Scannable Code128 barcode of the order's receipt reference
     * (``pos_reference``). Printing it on the sale receipt lets the cashier
     * scan the bill later in the Return/Exchange popup, where ``findOrder``
     * resolves the exact same reference.
     */
    get cbReturnBarcodeUrl() {
        const ref = this.order?.pos_reference;
        if (!ref) {
            return false;
        }
        const params = new URLSearchParams({
            barcode_type: "Code128",
            value: ref,
            width: "300",
            height: "70",
            humanreadable: "1",
        });
        return `/report/barcode/?${params.toString()}`;
    },
});
