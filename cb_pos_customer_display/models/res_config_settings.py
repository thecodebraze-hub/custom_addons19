# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_cb_show_loyalty_points = fields.Boolean(
        related="pos_config_id.cb_show_loyalty_points",
        readonly=False,
    )
