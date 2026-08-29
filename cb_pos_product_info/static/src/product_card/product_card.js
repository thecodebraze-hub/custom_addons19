import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";

patch(ProductCard.prototype, {
    setup() {
        super.setup(...arguments);
        this.cbPos = usePos();
        this.cbInfo = useState({
            open: false,
            loading: false,
            warehousesByProduct: {},
        });
    },

    get cbShowCost() {
        return !!this.cbPos?.config?.cb_show_product_cost;
    },

    get cbShowOnhand() {
        return !!this.cbPos?.config?.cb_show_product_onhand;
    },

    get cbShowCrossBranch() {
        return this.cbShowOnhand && !!this.cbPos?.config?.cb_show_cross_branch_onhand;
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

    cbFormatWarehouseQty(qty) {
        return this.env.utils.formatProductQty(qty ?? 0);
    },

    cbWarehouseLabel(wh) {
        if (!wh) {
            return "";
        }
        const name = wh.warehouse_name || "";
        const company = wh.company_name || "";
        if (company && name && company !== name) {
            return `${company} / ${name}`;
        }
        return name || company;
    },

    // Rows rendered inside the popover (one per variant).
    get cbInfoLines() {
        return this.cbVariants.map((variant) => ({
            id: variant.id,
            label: this.cbVariantLabel(variant),
            cost: this.cbFormatCost(variant),
            onhand: this.cbFormatOnhand(variant),
            warehouses: (this.cbInfo.warehousesByProduct[variant.id] || []).map((wh) => ({
                ...wh,
                label: this.cbWarehouseLabel(wh),
                qtyDisplay: this.cbFormatWarehouseQty(wh.qty),
            })),
        }));
    },

    async cbToggleInfo(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        this.cbInfo.open = !this.cbInfo.open;
        if (this.cbInfo.open && this.cbShowCrossBranch) {
            await this.cbLoadWarehouseOnhand();
        } else if (!this.cbInfo.open) {
            this.cbInfo.warehousesByProduct = {};
            this.cbInfo.loading = false;
        }
    },

    async cbLoadWarehouseOnhand() {
        const productIds = this.cbVariants.map((variant) => variant.id).filter(Boolean);
        if (!productIds.length || !this.cbPos?.config?.id) {
            return;
        }
        this.cbInfo.loading = true;
        try {
            const rows = await this.cbPos.data.call(
                "product.product",
                "cb_get_cross_branch_onhand",
                [productIds, this.cbPos.config.id]
            );
            const byProduct = {};
            for (const row of rows || []) {
                byProduct[row.product_id] = row.warehouses || [];
            }
            this.cbInfo.warehousesByProduct = byProduct;
        } catch (_error) {
            this.cbInfo.warehousesByProduct = {};
        } finally {
            this.cbInfo.loading = false;
        }
    },

    cbCloseInfo(ev) {
        ev.stopPropagation();
        this.cbInfo.open = false;
        this.cbInfo.warehousesByProduct = {};
        this.cbInfo.loading = false;
    },
});
