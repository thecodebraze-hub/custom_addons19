# -*- coding: utf-8 -*-
"""Link stock moves to POS return lines."""

from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    cb_pos_return_line_id = fields.Many2one(
        comodel_name="cb.pos.return.line",
        string="POS Return Line",
        index=True,
        copy=False,
        check_company=True,
    )
