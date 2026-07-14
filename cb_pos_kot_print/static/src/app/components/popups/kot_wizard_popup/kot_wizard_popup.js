import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { KotReceiptDisplay } from "../../kot_receipt/kot_receipt";

export class KotWizardPopup extends Component {
    static template = "cb_pos_kot_print.KotWizardPopup";
    static components = { Dialog, KotReceiptDisplay };
    static props = {
        order: { type: Object },
        close: { type: Function },
    };

    setup() {
        this.pos = usePos();
        this.kotReceiptRef = useRef("kotReceipt");
        this.state = useState({
            receiptsData: [],
            loading: true,
        });
        this.doPrintKot = useTrackedAsync(this._printKotAndFinish.bind(this));

        onMounted(async () => {
            const opts = this.props.order?.uiState?.pendingKotOpts || {};
            this.state.receiptsData = await this.pos.prepareKotReceipts(this.props.order, opts);
            this.state.loading = false;
        });
    }

    backToOrder() {
        const order = this.props.order;
        const onDone = order?.uiState?.onKotWizardDone;
        delete order?.uiState?.pendingKotOpts;
        delete order?.uiState?.pendingKotOrderChange;
        delete order?.uiState?.onKotWizardDone;
        this.props.close();
        onDone?.();
    }

    async _printKotAndFinish() {
        const order = this.props.order;
        if (!this.state.receiptsData.length) {
            return;
        }
        await this.pos.printKotReceipts(this.state.receiptsData);
        await this.pos.finishKotSend(order);
        this.props.close();
    }
}
