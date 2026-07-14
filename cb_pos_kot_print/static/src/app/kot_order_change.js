import { receiptLineGrouper } from "@point_of_sale/app/models/utils/order_change";

export function requiresKotProduct(product, models) {
    if (!product) {
        return false;
    }
    if (product.is_kot_product) {
        return true;
    }
    const modelStore = models || product.models;
    let template = product.product_tmpl_id;
    if (typeof template === "number" && modelStore) {
        template = modelStore["product.template"]?.get(template);
    }
    if (!template && product.model?.name === "product.template") {
        template = product;
    }
    return Boolean(template?.is_kot_product);
}

export function isKotLine(orderline) {
    const models = orderline.models;
    const product = orderline.getProduct();
    if (requiresKotProduct(product, models)) {
        return true;
    }
    if (requiresKotProduct(orderline.combo_parent_id?.product_id, models)) {
        return true;
    }
    return (
        orderline.combo_line_ids?.some((line) => requiresKotProduct(line.getProduct(), models)) ||
        false
    );
}

function getLastKotChange(order) {
    if (!order.uiState.lastKotChange) {
        order.uiState.lastKotChange = {
            lines: {},
            general_customer_note: "",
            internal_note: "",
        };
    }
    return order.uiState.lastKotChange;
}

function getLastKotChanges(order) {
    return getLastKotChange(order).lines;
}

/**
 * Delta logic for KOT: only products marked as KOT Product are included.
 */
export function getKotOrderChanges(order) {
    const oldChanges = getLastKotChanges(order);
    const changes = {};
    const noteUpdate = {};
    let changesCount = 0;
    let changeAbsCount = 0;

    for (const orderline of order.getOrderlines()) {
        const product = orderline.getProduct() || orderline.combo_parent_id?.product_id;
        const note = orderline.getNote();
        const customerNote = orderline.getCustomerNote();
        const lineKey = orderline.uuid;

        if (isKotLine(orderline)) {
            const key = Object.keys(getLastKotChanges(order)).find((k) =>
                k.startsWith(orderline.uuid)
            );
            const quantity = orderline.getQuantity();
            const relatedKey = key !== lineKey ? key : lineKey;
            const quantityDiff =
                (oldChanges[relatedKey] ? quantity - oldChanges[relatedKey].quantity : quantity) ||
                0;
            const noteChange =
                oldChanges[relatedKey] &&
                (oldChanges[relatedKey].note !== note ||
                    oldChanges[relatedKey].customer_note !== customerNote);

            const lineDetails = {
                uuid: orderline.uuid,
                name: orderline.getFullProductName(),
                basic_name: product?.name ?? "",
                isCombo: Boolean(orderline?.combo_line_ids?.length),
                combo_parent_uuid: orderline?.combo_parent_id?.uuid,
                product_id: product?.id,
                attribute_value_names: orderline.attribute_value_ids.map((a) => a.name),
                quantity: quantityDiff,
                note: note,
                customer_note: customerNote,
                pos_categ_id: product?.pos_categ_ids?.[0]?.id ?? 0,
                pos_categ_sequence: product?.pos_categ_ids?.[0]?.sequence ?? 0,
                display_name: product?.display_name ?? orderline.getFullProductName(),
                group: receiptLineGrouper.getGroup(orderline),
            };

            if (quantityDiff) {
                changes[lineKey] = lineDetails;
                changesCount += quantityDiff;
                changeAbsCount += Math.abs(quantityDiff);
                if (noteChange) {
                    lineDetails.quantity = oldChanges[relatedKey].quantity || 0;
                    noteUpdate[lineKey] = lineDetails;
                }
            } else if (noteChange) {
                lineDetails.quantity = orderline.qty;
                noteUpdate[lineKey] = lineDetails;
                changesCount += 1;
            }
        }
    }

    for (const [lineKey, lineResume] of Object.entries(getLastKotChanges(order))) {
        if (!order.models["pos.order.line"].getBy("uuid", lineResume["uuid"])) {
            const product = order.models["product.product"].get(lineResume["product_id"]);
            if (!requiresKotProduct(product, order.models)) {
                continue;
            }
            const quantity = isNaN(lineResume["quantity"]) ? 0 : lineResume["quantity"];
            if (!changes[lineKey]) {
                changes[lineKey] = {
                    uuid: lineResume["uuid"],
                    product_id: lineResume["product_id"],
                    name: lineResume["name"],
                    basic_name: lineResume["basic_name"],
                    display_name: lineResume["display_name"],
                    isCombo: Boolean(lineResume["isCombo"]),
                    combo_parent_uuid: lineResume["combo_parent_uuid"],
                    note: lineResume["note"],
                    customer_note: lineResume["customer_note"],
                    attribute_value_names: lineResume["attribute_value_names"],
                    group: lineResume["group"],
                    quantity: -quantity,
                };
                changeAbsCount += Math.abs(quantity);
                changesCount += quantity;
            } else {
                changes[lineKey]["quantity"] -= quantity;
            }
        }
    }

    const result = {
        nbrOfChanges: changeAbsCount,
        noteUpdate: noteUpdate,
        orderlines: changes,
        count: changesCount,
    };

    const lastKotChange = getLastKotChange(order);
    const lastGeneralCustomerNote = lastKotChange.general_customer_note || "";
    if (lastGeneralCustomerNote !== order.general_customer_note) {
        result.general_customer_note = order.general_customer_note;
    }
    const lastInternalNote = lastKotChange.internal_note || "";
    if (lastInternalNote !== order.internal_note) {
        result.internal_note = order.internal_note;
    }
    return result;
}

export function kotChangesToOrder(order, cancelled = false) {
    const toAdd = [];
    const toRemove = [];
    const orderChanges = getKotOrderChanges(order);
    const linesChanges = !cancelled
        ? Object.values(orderChanges.orderlines)
        : Object.values(getLastKotChanges(order));

    for (const lineChange of linesChanges) {
        if (lineChange["quantity"] > 0 && !cancelled) {
            toAdd.push(lineChange);
        } else {
            lineChange["quantity"] = Math.abs(lineChange["quantity"]);
            toRemove.push(lineChange);
        }
    }

    return {
        new: toAdd,
        cancelled: toRemove,
        noteUpdate: Object.values(orderChanges.noteUpdate),
        general_customer_note: orderChanges.general_customer_note,
        internal_note: orderChanges.internal_note,
    };
}
