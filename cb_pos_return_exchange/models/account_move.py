# -*- coding: utf-8 -*-
"""Link account moves to POS return documents."""

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    cb_pos_return_id = fields.Many2one(
        comodel_name="cb.pos.return",
        string="POS Return",
        index=True,
        copy=False,
        check_company=True,
    )
    cb_pos_return_voucher_id = fields.Many2one(
        comodel_name="cb.pos.return.voucher",
        string="POS Return Voucher",
        index=True,
        copy=False,
        check_company=True,
    )
    cb_original_invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Original Customer Invoice",
        index=True,
        copy=False,
        check_company=True,
        help="Posted invoice reversed by this credit note.",
    )
