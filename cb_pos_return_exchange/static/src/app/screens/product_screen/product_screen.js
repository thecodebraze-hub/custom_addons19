/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import "../../load_services";

patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        const handled = await this.pos.returnBarcode.processScan(code, { screen: "product" });
        if (handled) {
            this.numberBuffer.reset();
            return;
        }
        return super._barcodeProductAction(code);
    },
});
