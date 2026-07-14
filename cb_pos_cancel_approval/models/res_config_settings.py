# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_cb_require_cancel_approval = fields.Boolean(
        related="pos_config_id.cb_require_cancel_approval",
        readonly=False,
    )
