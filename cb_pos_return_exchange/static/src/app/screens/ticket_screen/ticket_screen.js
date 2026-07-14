/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import "../../load_services";

patch(TicketScreen.prototype, {
    setup() {
        super.setup(...arguments);
        useBarcodeReader({
            product: (parsed) => this.pos.returnBarcode.processScan(parsed, { screen: "ticket" }),
            weight: (parsed) => this.pos.returnBarcode.processScan(parsed, { screen: "ticket" }),
            quantity: (parsed) => this.pos.returnBarcode.processScan(parsed, { screen: "ticket" }),
            price: (parsed) => this.pos.returnBarcode.processScan(parsed, { screen: "ticket" }),
            gs1: (parsed) => {
                const product = parsed?.find?.((p) => p.type === "product");
                if (product) {
                    this.pos.returnBarcode.processScan(product, { screen: "ticket" });
                }
            },
        });
    },
});
