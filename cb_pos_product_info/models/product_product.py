from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config):
        fields = super()._load_pos_data_fields(config)
        if config.cb_show_product_onhand and "qty_available" not in fields:
            fields.append("qty_available")
        return fields

    @api.model
    def cb_get_cross_branch_onhand(self, product_ids, pos_config_id):
        """Return warehouse-wise on-hand across company branches for POS popup."""
        config = self.env["pos.config"].browse(pos_config_id)
        if not config.exists() or not config.cb_show_cross_branch_onhand:
            return []

        company = config.company_id
        root = company
        while root.parent_id:
            root = root.parent_id
        companies = self.env["res.company"].sudo().search([("id", "child_of", root.id)])
        warehouses = self.env["stock.warehouse"].sudo().search(
            [("company_id", "in", companies.ids)],
            order="company_id, name",
        )
        current_wh_id = config.warehouse_id.id

        result = []
        for product in self.browse(product_ids):
            lines = []
            for warehouse in warehouses:
                qty = (
                    product.sudo()
                    .with_company(warehouse.company_id)
                    .with_context(warehouse_id=warehouse.id)
                    .qty_available
                )
                lines.append({
                    "warehouse_id": warehouse.id,
                    "warehouse_name": warehouse.name,
                    "company_name": warehouse.company_id.name,
                    "qty": qty,
                    "is_current": warehouse.id == current_wh_id,
                })
            lines.sort(
                key=lambda line: (
                    not line["is_current"],
                    -line["qty"],
                    line["company_name"],
                    line["warehouse_name"],
                )
            )
            result.append({
                "product_id": product.id,
                "warehouses": lines,
            })
        return result
