from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    cb_show_product_cost = fields.Boolean(
        string="Show Product Cost on Card",
        help="Display the product cost inside the info icon on POS product cards.",
    )
    cb_show_product_onhand = fields.Boolean(
        string="Show On-hand Qty on Card",
        help="Display the on-hand quantity inside the info icon on POS product cards.",
    )
