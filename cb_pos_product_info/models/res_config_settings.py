from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_cb_show_product_cost = fields.Boolean(
        related="pos_config_id.cb_show_product_cost",
        readonly=False,
    )
    pos_cb_show_product_onhand = fields.Boolean(
        related="pos_config_id.cb_show_product_onhand",
        readonly=False,
    )
    pos_cb_show_cross_branch_onhand = fields.Boolean(
        related="pos_config_id.cb_show_cross_branch_onhand",
        readonly=False,
    )
