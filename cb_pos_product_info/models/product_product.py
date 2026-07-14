from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config):
        fields = super()._load_pos_data_fields(config)
        if config.cb_show_product_onhand and "qty_available" not in fields:
            fields.append("qty_available")
        return fields
