import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { isKotLine } from "../kot_order_change";

patch(PosOrder.prototype, {
    updateLastKotChange() {
        const lastKotChange = this.uiState.lastKotChange || { lines: {} };
        if (!this.uiState.lastKotChange) {
            this.uiState.lastKotChange = lastKotChange;
        }
        if (!lastKotChange.lines) {
            lastKotChange.lines = {};
        }

        this.lines.forEach((line) => {
            if (!isKotLine(line)) {
                return;
            }

            if (this.uiState.lastKotChange.lines[line.preparationKey]) {
                this.uiState.lastKotChange.lines[line.preparationKey] = {
                    ...this.uiState.lastKotChange.lines[line.preparationKey],
                    quantity: line.getQuantity(),
                    note: line.getNote(),
                    customer_note: line.getCustomerNote(),
                };
            } else {
                const product = line.getProduct();
                this.uiState.lastKotChange.lines[line.preparationKey] = {
                    attribute_value_names: line.attribute_value_ids.map((a) => a.name),
                    uuid: line.uuid,
                    isCombo: Boolean(line?.combo_line_ids?.length),
                    combo_parent_uuid: line?.combo_parent_id?.uuid,
                    product_id: product.id,
                    name: line.getFullProductName(),
                    basic_name: product.name,
                    display_name: product.display_name,
                    note: line.getNote(),
                    quantity: line.getQuantity(),
                    customer_note: line.getCustomerNote(),
                };
            }
        });

        for (const [key, change] of Object.entries(this.uiState.lastKotChange.lines)) {
            const orderline = this.models["pos.order.line"].getBy("uuid", change.uuid);
            const lineNote = orderline?.note;
            const changeNote = change?.note;
            if (!orderline || (lineNote && changeNote && changeNote.trim() !== lineNote.trim())) {
                delete this.uiState.lastKotChange.lines[key];
            }
        }

        this.uiState.lastKotChange.general_customer_note = this.general_customer_note;
        this.uiState.lastKotChange.internal_note = this.internal_note;
    },
});
