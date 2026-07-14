import { patch } from "@web/core/utils/patch";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

patch(PosOrderline.prototype, {
    isServiceChargeLine() {
        const serviceCharge = this.config.service_charge_id;
        if (!serviceCharge) {
            return false;
        }
        let product = serviceCharge.product_id;
        if (typeof product === "number") {
            product = this.models["product.product"].get(product);
        }
        return Boolean(product && this.product_id?.id === product.id);
    },

    delete(opts) {
        const wasServiceCharge = this.isServiceChargeLine();
        const order = this.order_id;
        const hadServiceCharge = order?.service_charge_rate > 0;
        const result = super.delete(opts);
        if (wasServiceCharge && order) {
            order.service_charge_rate = 0;
            order.service_charge_amount = 0;
        } else if (hadServiceCharge && order) {
            order._recomputeServiceChargeAmount();
        }
        return result;
    },

    _triggerServiceChargeRecalc() {
        const order = this.order_id;
        if (order?.service_charge_rate > 0 && !this.isServiceChargeLine()) {
            order._recomputeServiceChargeAmount();
        }
    },

    setQuantity(...args) {
        const result = super.setQuantity(...args);
        this._triggerServiceChargeRecalc();
        return result;
    },

    setDiscount(...args) {
        const result = super.setDiscount(...args);
        this._triggerServiceChargeRecalc();
        return result;
    },

    setUnitPrice(...args) {
        const result = super.setUnitPrice(...args);
        if (!this.isServiceChargeLine()) {
            this._triggerServiceChargeRecalc();
        }
        return result;
    },
});
