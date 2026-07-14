/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { CbCancelApprovalPopup } from "./cancel_approval_popup/cancel_approval_popup";

patch(PosStore.prototype, {
    async cbRequestCancelApproval(context = {}) {
        const approval = await makeAwaitable(this.dialog, CbCancelApprovalPopup, context);
        if (!approval?.approved) {
            return false;
        }
        try {
            const result = await this.data.call(
                "pos.config",
                "cb_log_cancel_approval",
                [
                    [this.config.id],
                    {
                        action_type: context.actionType || "cancel_order",
                        session_id: this.session?.id || false,
                        manager_id: approval.manager_id,
                        order_reference: context.orderReference || "",
                        product_name: context.productName || "",
                        amount: context.amount || 0,
                        reason: approval.reason || "",
                    },
                ]
            );
            if (!result?.success) {
                this.notification.add(result?.error || "Could not save approval.", {
                    type: "danger",
                });
                return false;
            }
        } catch (error) {
            this.notification.add(
                error?.data?.message || error?.message || "Could not save approval.",
                { type: "danger" }
            );
            return false;
        }
        return true;
    },

    async beforeDeleteOrder(order, options) {
        if (this.config.cb_require_cancel_approval && order.getOrderlines().length > 0) {
            return this.cbRequestCancelApproval({
                actionType: "cancel_order",
                orderReference: order.pos_reference,
                amount: order.priceIncl,
            });
        }
        return super.beforeDeleteOrder(order, options);
    },
});
