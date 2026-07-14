/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { detectBarcodeFormat } from "../../../services/barcode_utils";

const TYPE_LABELS = {
    product: _t("Product Barcode"),
    voucher: _t("Voucher Barcode"),
    return: _t("Return Barcode"),
    order: _t("Receipt / Order Barcode"),
};

const TYPE_ICONS = {
    product: "fa-cube",
    voucher: "fa-ticket",
    return: "fa-reply",
    order: "fa-file-text-o",
};

export class BarcodeActionPopup extends Component {
    static template = "cb_pos_return_exchange.BarcodeActionPopup";
    static components = { Dialog };
    static props = {
        pos: { type: Object },
        classification: { type: Object },
        getPayload: { type: Function },
        close: { type: Function },
    };

    get typeLabel() {
        return TYPE_LABELS[this.props.classification.barcode_type] || _t("Barcode");
    }

    get typeIcon() {
        return TYPE_ICONS[this.props.classification.barcode_type] || "fa-barcode";
    }

    get formatLabel() {
        const format = this.props.classification.barcode_format || detectBarcodeFormat(
            this.props.classification.barcode
        );
        return format.toUpperCase().replace("_", "-");
    }

    selectAction(actionId) {
        this.props.getPayload({ action: actionId });
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
