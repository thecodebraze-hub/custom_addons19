import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { kotChangesToOrder, getKotOrderChanges } from "../kot_order_change";
import { _t } from "@web/core/l10n/translation";
import { formatList } from "@web/core/l10n/utils/format_list";
import { renderToElement } from "@web/core/utils/render";
import { KotWizardPopup } from "../components/popups/kot_wizard_popup/kot_wizard_popup";

const { DateTime } = luxon;

patch(PosStore.prototype, {
    _hasKotChanges(order, opts = {}) {
        if (opts.explicitReprint) {
            return Boolean(order.uiState.lastPrints?.length);
        }
        const orderChange = kotChangesToOrder(order, opts.cancelled);
        return Boolean(
            orderChange.new.length ||
                orderChange.cancelled.length ||
                orderChange.noteUpdate.length ||
                orderChange.internal_note ||
                orderChange.general_customer_note
        );
    },

    getKotCategoryCount(order = this.getOrder()) {
        if (!order) {
            return [];
        }
        const orderChanges = getKotOrderChanges(order);
        const linesChanges = orderChanges.orderlines;
        const uncategorized = { count: 0, name: _t("KOT") };

        const categories = Object.values(linesChanges).reduce((acc, curr) => {
            const product = this.models["product.product"].get(curr.product_id);
            let template = product?.product_tmpl_id;
            if (typeof template === "number") {
                template = this.models["product.template"]?.get(template);
            }
            const productCategories = template?.pos_categ_ids || [];

            if (productCategories.length) {
                for (const category of productCategories.slice(0, 1)) {
                    if (!acc[category.id]) {
                        acc[category.id] = {
                            count: curr.quantity,
                            name: category.name,
                        };
                    } else {
                        acc[category.id].count += curr.quantity;
                    }
                }
            } else {
                uncategorized.count += curr.quantity;
            }
            return acc;
        }, {});

        const noteCount = ["general_customer_note", "internal_note"].reduce(
            (count, note) => count + (note in orderChanges ? 1 : 0),
            0
        );

        const nbNoteChange = Object.keys(orderChanges.noteUpdate).length;
        if (nbNoteChange) {
            categories.noteUpdate = { count: nbNoteChange, name: _t("Note") };
        }

        const result = [...Object.values(categories)];
        if (uncategorized.count) {
            result.push(uncategorized);
        }
        if (noteCount > 0) {
            result.push({ count: noteCount, name: _t("Message") });
        }
        return result;
    },

    _openKotWizard(order, opts = {}) {
        order.uiState.pendingKotOpts = opts;
        this.dialog.add(KotWizardPopup, { order });
    },

    async submitKot() {
        const order = this.getOrder();
        await this.ensureGuestCustomerCount(order);
        if (!this._hasKotChanges(order)) {
            return;
        }
        this._openKotWizard(order);
    },

    async reprintOrder() {
        const order = this.getOrder();
        if (this.config.iface_kot_print && this._hasKotChanges(order, { explicitReprint: true })) {
            this._openKotWizard(order, { explicitReprint: true });
            return;
        }
        await super.reprintOrder(...arguments);
    },

    async prepareKotReceipts(order, opts = {}) {
        const reprint = Boolean(opts.explicitReprint);
        let orderChange = kotChangesToOrder(order, opts.cancelled);

        const hasChanges =
            orderChange.new.length ||
            orderChange.cancelled.length ||
            orderChange.noteUpdate.length ||
            orderChange.internal_note ||
            orderChange.general_customer_note;

        if (!hasChanges) {
            if (reprint && order.uiState.lastPrints?.length) {
                orderChange = order.uiState.lastPrints.at(-1);
            } else {
                return [];
            }
        }

        this._formatKotChangeNotes(orderChange);
        order.uiState.pendingKotOrderChange = orderChange;

        return [this._buildKotReceiptData(order, orderChange, reprint)];
    },

    _getKotCompany(order) {
        return order?.company || this.company;
    },

    _buildKotReceiptData(order, orderChange, reprint) {
        const lines = [];
        const pushLine = (line, prefix = "") => {
            const name = prefix + (line.name || line.basic_name || "");
            const note = line.customer_note || line.note || "";
            lines.push({
                qty: line.quantity,
                name,
                note: typeof note === "string" ? note.replace(/\n/g, ", ") : "",
            });
        };

        for (const line of orderChange.new) {
            pushLine(line);
        }
        for (const line of orderChange.cancelled) {
            pushLine(line, "(-) ");
        }
        for (const line of orderChange.noteUpdate) {
            pushLine(line, "(*) ");
        }

        return {
            company: this._getKotCompany(order),
            table_number: order.table_id?.table_number || "",
            order_reference: order.getName(),
            date_time: DateTime.now().toFormat("dd/MM/yyyy hh:mm a"),
            lines,
            reprint,
        };
    },

    async printKotReceipts(receiptsData) {
        let lastResult;
        for (const data of receiptsData) {
            const receipt = renderToElement("cb_pos_kot_print.KotReceipt", { data });
            lastResult = await this.printer.printHtml(receipt, this.printOptions);
            if (lastResult?.warningCode) {
                this.displayPrinterWarning(lastResult, _t("Receipt Printer"));
            }
        }
        return lastResult;
    },

    async finishKotSend(order) {
        const opts = order.uiState.pendingKotOpts || {};
        const orderChange = order.uiState.pendingKotOrderChange;

        if (
            !opts.explicitReprint &&
            orderChange &&
            (orderChange.new?.length ||
                orderChange.cancelled?.length ||
                orderChange.noteUpdate?.length ||
                orderChange.internal_note ||
                orderChange.general_customer_note)
        ) {
            order.uiState.lastPrints = order.uiState.lastPrints || [];
            order.uiState.lastPrints.push(orderChange);
        }

        order.updateLastKotChange();
        delete order.uiState.pendingKotOpts;
        delete order.uiState.pendingKotOrderChange;

        this._notifyKotSent(order, opts);

        const onDone = order.uiState.onKotWizardDone;
        delete order.uiState.onKotWizardDone;
        onDone?.();
    },

    _notifyKotSent(order, opts = {}) {
        const orderChange =
            order.uiState.lastPrints?.at(-1) || order.uiState.pendingKotOrderChange;
        if (!orderChange) {
            return;
        }
        if (opts.explicitReprint) {
            this.notification.add(_t("KOT reprinted"), { type: "success" });
            return;
        }
        const items = (orderChange.new || []).map(
            (line) => `${line.quantity} ${line.basic_name || line.name}`
        );
        if (items.length) {
            const summary = formatList(items);
            this.notification.add(_t("KOT sent: %s", summary), { type: "success" });
        } else if (orderChange.cancelled?.length) {
            this.notification.add(_t("KOT cancellation sent"), { type: "success" });
        } else if (orderChange.noteUpdate?.length) {
            this.notification.add(_t("KOT note update sent"), { type: "success" });
        } else {
            this.notification.add(_t("KOT sent"), { type: "success" });
        }
    },

    _formatKotChangeNotes(orderChange) {
        for (const changeItem of [
            ...orderChange.new,
            ...orderChange.cancelled,
            ...orderChange.noteUpdate,
        ]) {
            changeItem.note = this.getStrNotes(changeItem.note || "[]");
        }
    },
});
