# -*- coding: utf-8 -*-
"""Link stock pickings to POS return documents."""

from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    cb_pos_return_id = fields.Many2one(
        comodel_name="cb.pos.return",
        string="POS Return",
        index=True,
        copy=False,
        check_company=True,
    )
