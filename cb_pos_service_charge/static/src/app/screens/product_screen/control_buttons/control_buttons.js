import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";

patch(ControlButtons.prototype, {
    get showServiceChargeButton() {
        const order = this.currentOrder;
        const hasCharge = order?.service_charge_rate > 0 || order?.hasServiceCharge;
        return (
            this.pos.config.iface_service_charge &&
            this.pos.getServiceChargeConfig() &&
            this.pos.cashier._role !== "minimal" &&
            Boolean(order) &&
            (!order.isEmpty() || hasCharge)
        );
    },
    get serviceChargeLabel() {
        const order = this.currentOrder;
        if (order?.service_charge_rate > 0) {
            return _t("Service Charge (%s%)", order.service_charge_rate);
        }
        return _t("% Service Charge");
    },
    async clickServiceCharge() {
        await this.pos.openServiceChargeWizard();
        this.props.close?.();
    },
});
