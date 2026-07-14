import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.doSubmitKot = useTrackedAsync(() => this.pos.submitKot());
    },
    get showKotBar() {
        const order = this.currentOrder;
        return (
            this.pos.config.iface_kot_print &&
            order &&
            !order.isRefund &&
            !order.isEmpty() &&
            this.pos._hasKotChanges(order)
        );
    },
    get displayKotCount() {
        if (!this.pos.config.iface_kot_print) {
            return [];
        }
        return this.pos.getKotCategoryCount(this.currentOrder).slice(0, 4);
    },
    get isKotCountOverflow() {
        return this.pos.getKotCategoryCount(this.currentOrder).length > 4;
    },
});
