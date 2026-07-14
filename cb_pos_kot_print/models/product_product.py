from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    is_kot_product = fields.Boolean(
        related="product_tmpl_id.is_kot_product",
        store=True,
        readonly=False,
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return list(super()._load_pos_data_fields(config)) + ["is_kot_product"]
