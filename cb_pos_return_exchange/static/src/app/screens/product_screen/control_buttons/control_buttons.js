/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";
import "../../../load_services";

patch(ControlButtons.prototype, {
    async clickCbExchange() {
        await this.pos.openExchangeFlow();
        this.props.close?.();
    },

    async clickCbReturnHistory() {
        const partner = this.pos.getOrder()?.getPartner?.();
        await this.pos.openHistoryPopup({ partnerId: partner?.id || false });
        this.props.close?.();
    },

    get showCbReturnButtons() {
        return (
            this.pos.cashier?._role !== "minimal" &&
            this.pos._cbReturnModuleEnabled !== false
        );
    },
});
