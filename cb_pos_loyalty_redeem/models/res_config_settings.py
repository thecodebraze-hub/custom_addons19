# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_cb_loyalty_redeem_enabled = fields.Boolean(
        related="pos_config_id.cb_loyalty_redeem_enabled",
        readonly=False,
    )
    pos_cb_loyalty_program_id = fields.Many2one(
        related="pos_config_id.cb_loyalty_program_id",
        readonly=False,
    )
    pos_cb_loyalty_redeem_product_id = fields.Many2one(
        related="pos_config_id.cb_loyalty_redeem_product_id",
        readonly=False,
    )
    pos_cb_loyalty_point_rate = fields.Float(
        related="pos_config_id.cb_loyalty_point_rate",
        readonly=False,
    )
    pos_cb_loyalty_min_points = fields.Float(
        related="pos_config_id.cb_loyalty_min_points",
        readonly=False,
    )
