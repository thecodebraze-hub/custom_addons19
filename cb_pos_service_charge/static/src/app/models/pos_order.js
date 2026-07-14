import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";

patch(PosOrder.prototype, {
    get hasServiceCharge() {
        const line = this.getServiceChargeLine();
        const amount = line?.prices?.total_included_currency ?? this.service_charge_amount;
        return Boolean(amount);
    },

    get serviceChargeAmount() {
        if (this.service_charge_amount) {
            return this.service_charge_amount;
        }
        return this.getServiceChargeLine()?.prices?.total_included_currency || 0;
    },

    get serviceChargeLabel() {
        const rate = this.service_charge_rate;
        if (rate > 0) {
            return `Service Charge (${rate}%)`;
        }
        return "Service Charge";
    },

    get currencyServiceChargeAmount() {
        const currency = this.currency;
        if (!currency) {
            return "";
        }
        return formatCurrency(this.serviceChargeAmount ?? 0, currency);
    },

    getServiceChargeProduct() {
        const serviceCharge = this.config.service_charge_id;
        if (!serviceCharge) {
            return null;
        }
        const product = serviceCharge.product_id;
        if (typeof product === "number") {
            return this.models["product.product"].get(product);
        }
        return product;
    },

    getServiceChargeLine() {
        const product = this.getServiceChargeProduct();
        if (!product) {
            return null;
        }
        return this.lines.find((line) => line.product_id?.id === product.id);
    },

    _isExcludedFromServiceChargeBase(line) {
        if (line.isServiceChargeLine?.()) {
            return true;
        }
        if (line.isTipLine?.()) {
            return true;
        }
        if (line.isGlobalDiscountLine?.()) {
            return true;
        }
        const discountProduct = this.config.discount_product_id;
        if (discountProduct) {
            const discountProductId =
                typeof discountProduct === "object" ? discountProduct.id : discountProduct;
            if (line.product_id?.id === discountProductId) {
                return true;
            }
        }
        return false;
    },

    getServiceChargeBase() {
        let base = 0;
        for (const line of this.lines) {
            if (this._isExcludedFromServiceChargeBase(line)) {
                continue;
            }
            base += line.prices?.total_included_currency ?? 0;
        }
        return base;
    },

    _recomputeServiceChargeAmount() {
        if (!this.service_charge_rate) {
            return;
        }
        const line = this.getServiceChargeLine();
        if (!line) {
            return;
        }
        const amount = this.currency.round(
            this.getServiceChargeBase() * (this.service_charge_rate / 100)
        );
        if (amount <= 0) {
            line.delete();
            this.service_charge_rate = 0;
            this.service_charge_amount = 0;
            return;
        }
        line.setUnitPrice(amount);
        this.service_charge_amount = amount;
    },
});
