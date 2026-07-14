/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onMounted } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { BackButton } from "@point_of_sale/app/screens/product_screen/action_pad/back_button/back_button";
import "../../load_services";

export class ExchangeScreen extends Component {
    static storeOnOrder = false;
    static template = "cb_pos_return_exchange.ExchangeScreen";
    static components = { BackButton };
    static props = {
        returnId: { type: Number, optional: true },
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.api = this.pos.returnApi;

        this.state = useState({
            loading: false,
            error: "",
            returnId: this.props.returnId || this.pos.getLastReturnId() || false,
            returnAmount: 0,
            replacementTotal: 0,
            difference: 0,
            customerPayment: 0,
            voucherUsed: false,
            autoComplete: true,
        });

        onMounted(async () => {
            this.refreshTotals();
            if (this.state.returnId) {
                await this.loadReturnAmount();
            }
        });
    }

    formatMoney(amount) {
        return this.api.formatMoney(amount);
    }

    get currentOrder() {
        return this.pos.getOrder();
    }

    refreshTotals() {
        const order = this.currentOrder;
        this.state.replacementTotal = order?.getTotalWithTax?.() || order?.amount_total || 0;
        this.state.difference = this.state.replacementTotal - (this.state.returnAmount || 0);
    }

    async loadReturnAmount() {
        if (!this.state.returnId) {
            this.state.error = _t("Select a return to exchange against.");
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        try {
            const records = await this.pos.data.searchRead(
                "cb.pos.return",
                [["id", "=", this.state.returnId]],
                ["amount_total", "name", "state"],
                { limit: 1 }
            );
            const ret = records?.[0];
            if (!ret) {
                this.state.error = _t("Return not found.");
                return;
            }
            this.state.returnAmount = ret.amount_total;
            this.refreshTotals();
        } catch (error) {
            this.state.error = error?.message || _t("Unable to load return.");
        } finally {
            this.state.loading = false;
        }
    }

    async completeExchange() {
        const order = this.currentOrder;
        if (!order?.lines?.length) {
            this.state.error = _t("Add replacement products to the current order first.");
            return;
        }
        if (!this.state.returnId) {
            this.state.error = _t("A return document is required.");
            return;
        }
        if (!order.id || order.id < 0) {
            this.state.error = _t("Sync the replacement order before completing the exchange.");
            return;
        }

        this.state.loading = true;
        this.state.error = "";
        try {
            const result = await this.api.createExchange({
                return_id: this.state.returnId,
                replacement_order_id: order.id,
                customer_payment: this.state.customerPayment,
                voucher_used: this.state.voucherUsed,
                auto_complete: this.state.autoComplete,
            });
            if (!result?.id) {
                this.state.error = result?.error || _t("Exchange failed.");
                return;
            }
            this.notification.add(
                _t("Exchange %(name)s created.", { name: result.name }),
                { type: "success" }
            );
            if (result.id) {
                await this.pos.printExchangeReceipt(result.id);
            }
            this.pos.clearPendingExchange();
            if (result.voucher_id) {
                const voucherResult = await this.api.generateVoucher(this.state.returnId);
                if (voucherResult?.success && voucherResult.voucher) {
                    await this.pos.showVoucherPopup(voucherResult.voucher);
                }
            }
            this.back();
        } finally {
            this.state.loading = false;
        }
    }

    openReturnScreen() {
        this.pos.openReturnScreen();
    }

    back() {
        this.pos.navigate("ProductScreen", { orderUuid: this.currentOrder?.uuid });
    }
}

registry.category("pos_pages").add("CbExchangeScreen", {
    name: "CbExchangeScreen",
    component: ExchangeScreen,
    route: `/pos/ui/${odoo.pos_config_id}/exchange`,
    params: {},
});
