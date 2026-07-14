import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { ServiceChargePopup } from "../components/popups/service_charge_popup/service_charge_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";

patch(PosStore.prototype, {
    getServiceChargeConfig() {
        if (!this.config.iface_service_charge) {
            return null;
        }
        let serviceCharge = this.config.service_charge_id;
        if (typeof serviceCharge === "number") {
            serviceCharge = this.models["pos.service.charge"].get(serviceCharge);
        }
        if (!serviceCharge) {
            serviceCharge =
                this.models["pos.service.charge"]
                    .getAll()
                    .find((record) => record.company_id?.id === this.company?.id) ||
                this.models["pos.service.charge"].getFirst();
        }
        return serviceCharge || null;
    },

    _isServiceChargeProduct(product) {
        const serviceCharge = this.getServiceChargeConfig();
        if (!serviceCharge?.product_id || !product) {
            return false;
        }
        const productId = typeof product === "object" ? product.id : product;
        let serviceProduct = serviceCharge.product_id;
        if (typeof serviceProduct === "number") {
            serviceProduct = this.models["product.product"].get(serviceProduct);
        }
        return serviceProduct && productId === serviceProduct.id;
    },

    async _updateServiceChargeIfApplied() {
        const order = this.getOrder();
        if (order?.service_charge_rate > 0) {
            await this.setServiceCharge(order.service_charge_rate);
        }
    },

    async openServiceChargeWizard() {
        const order = this.getOrder();
        if (!order || order.isEmpty()) {
            this.notification.add(_t("Add products before applying a service charge."), {
                type: "warning",
            });
            return;
        }
        if (!this.getServiceChargeConfig()) {
            this.notification.add(_t("Service charge is not configured for this POS."), {
                type: "warning",
            });
            return;
        }
        const startingRate =
            order.service_charge_rate > 0
                ? order.service_charge_rate
                : this.getServiceChargeConfig()?.rate ?? 10;
        const payload = await makeAwaitable(this.dialog, ServiceChargePopup, {
            order,
            startingRate,
        });
        if (!payload) {
            return;
        }
        await this.setServiceCharge(payload.rate);
    },

    async setServiceCharge(rate) {
        const order = this.getOrder();
        const serviceChargeConfig = this.getServiceChargeConfig();
        let product = serviceChargeConfig?.product_id;
        if (typeof product === "number") {
            product = this.models["product.product"].get(product);
        }
        if (!order || !product) {
            return;
        }

        if (!rate || rate <= 0) {
            const line = order.getServiceChargeLine();
            line?.delete();
            order.service_charge_rate = 0;
            order.service_charge_amount = 0;
            return;
        }

        const base = order.getServiceChargeBase();
        const amount = this.currency.round(base * (rate / 100));

        let line = order.getServiceChargeLine();
        if (line) {
            line.setUnitPrice(amount);
        } else if (amount > 0) {
            line = await this.addLineToCurrentOrder(
                {
                    product_id: product,
                    price_unit: amount,
                    product_tmpl_id: product.product_tmpl_id,
                },
                {},
                false
            );
        }
        if (line) {
            line.full_product_name = `Service Charge (${rate}%)`;
        }

        order.service_charge_rate = rate;
        order.service_charge_amount = amount;
    },

    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        const result = await super.addLineToCurrentOrder(vals, opts, configure);
        if (!this._isServiceChargeProduct(vals.product_id)) {
            await this._updateServiceChargeIfApplied();
        }
        return result;
    },

    async preSyncAllOrders(orders) {
        for (const order of orders) {
            if (order.service_charge_rate > 0) {
                order._recomputeServiceChargeAmount?.();
            }
        }
        return super.preSyncAllOrders(...arguments);
    },
});
