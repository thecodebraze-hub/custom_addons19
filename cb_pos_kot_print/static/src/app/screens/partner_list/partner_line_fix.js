import { patch } from "@web/core/utils/patch";
import { PartnerLine } from "@point_of_sale/app/screens/partner_list/partner_line/partner_line";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { PosStore } from "@point_of_sale/app/services/pos_store";

const EMPTY_PARTNER_INFOS = Object.freeze({
    totalDue: 0,
    posOrdersAmountDue: 0,
    invoicesAmountDue: 0,
    remainingDue: 0,
    totalWithCart: 0,
    creditLimit: 0,
    useLimit: false,
    overDue: false,
});

function safePartnerInfos(pos, partner) {
    if (!pos || typeof pos.getPartnerCredit !== "function") {
        return { ...EMPTY_PARTNER_INFOS };
    }
    try {
        const infos = pos.getPartnerCredit(partner);
        if (infos && typeof infos.overDue === "boolean") {
            return infos;
        }
    } catch {
        // Fall through to default values.
    }
    return { ...EMPTY_PARTNER_INFOS };
}

patch(PosStore.prototype, {
    getPartnerCredit(partner) {
        try {
            const infos = super.getPartnerCredit(partner);
            if (infos && typeof infos.overDue === "boolean") {
                return infos;
            }
        } catch {
            // Fall through to default values.
        }
        const order = this.getOrder();
        return {
            ...EMPTY_PARTNER_INFOS,
            totalWithCart: order ? this.currency.round(order.priceIncl || 0) : 0,
        };
    },
});

patch(PartnerLine.prototype, {
    get partnerInfos() {
        return safePartnerInfos(this.pos, this.props.partner);
    },
});

patch(PartnerList.prototype, {
    get partnerInfos() {
        return safePartnerInfos(this.pos, this.props.partner);
    },
});
