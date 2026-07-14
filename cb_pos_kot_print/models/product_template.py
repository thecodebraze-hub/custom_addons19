from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_kot_product = fields.Boolean(
        string="KOT Product",
        default=False,
        help="Include this product on Kitchen Order Tickets when sent from the Point of Sale. "
        "Applies to all variants of this product.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if fields_list:
            return list(fields_list) + ["is_kot_product"]
        return fields_list
