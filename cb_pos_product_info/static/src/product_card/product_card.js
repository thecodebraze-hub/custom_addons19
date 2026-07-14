import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";

patch(ProductCard.prototype, {
    setup() {
        super.setup(...arguments);
        this.cbPos = usePos();
        this.cbInfo = useState({ open: false });
    },

    get cbShowCost() {
        return !!this.cbPos?.config?.cb_show_product_cost;
    },

    get cbShowOnhand() {
        return !!this.cbPos?.config?.cb_show_product_onhand;
    },

    get cbHasInfo() {
        return this.cbShowCost || this.cbShowOnhand;
    },

    // On the product grid the card represents a product.template, so read the
    // individual variants (product.product) to expose per-variant figures.
    get cbVariants() {
        const product = this.props.product;
        if (!product) {
            return [];
        }
        const variants = (product.product_variant_ids || []).filter(Boolean);
        if (variants.length) {
            return variants;
        }
        return [product];
    },

    get cbIsMultiVariant() {
        return this.cbVariants.length > 1;
    },

    cbVariantLabel(variant) {
        const values = variant.product_template_attribute_value_ids;
        if (values && values.length) {
            return values.map((v) => v.name).join(", ");
        }
        return variant.display_name || variant.name || "";
    },

    cbFormatCost(variant) {
        return this.env.utils.formatCurrency(variant.standard_price ?? 0);
    },

    cbFormatOnhand(variant) {
        return this.env.utils.formatProductQty(variant.qty_available ?? 0);
    },

    // Rows rendered inside the popover (one per variant).
    get cbInfoLines() {
        return this.cbVariants.map((variant) => ({
            id: variant.id,
            label: this.cbVariantLabel(variant),
            cost: this.cbFormatCost(variant),
            onhand: this.cbFormatOnhand(variant),
        }));
    },

    cbToggleInfo(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        this.cbInfo.open = !this.cbInfo.open;
    },

    cbCloseInfo(ev) {
        ev.stopPropagation();
        this.cbInfo.open = false;
    },
});
