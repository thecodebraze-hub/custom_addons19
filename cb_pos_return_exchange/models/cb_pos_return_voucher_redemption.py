# -*- coding: utf-8 -*-
"""Voucher redemption history for audit and partial usage tracking."""

from odoo import fields, models


class CbPosReturnVoucherRedemption(models.Model):
    """Single voucher redemption event against a POS order."""

    _name = "cb.pos.return.voucher.redemption"
    _description = "POS Return Voucher Redemption"
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(readonly=True, default="New", index=True)
    voucher_id = fields.Many2one(
        comodel_name="cb.pos.return.voucher",
        string="Voucher",
        required=True,
        ondelete="cascade",
        index=True,
    )
    pos_order_id = fields.Many2one(
        comodel_name="pos.order",
        string="POS Order",
        required=True,
        index=True,
        check_company=True,
    )
    session_id = fields.Many2one(
        comodel_name="pos.session",
        string="POS Session",
        index=True,
        check_company=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Cashier",
        default=lambda self: self.env.user,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="voucher_id.currency_id",
        store=True,
        readonly=True,
    )
    amount = fields.Monetary(
        string="Redeemed Amount",
        currency_field="currency_id",
        required=True,
    )
    remainder_voucher_id = fields.Many2one(
        comodel_name="cb.pos.return.voucher",
        string="Remainder Voucher",
        index=True,
        ondelete="set null",
        help="Child voucher issued for the unused balance, when applicable.",
    )
    note = fields.Char()
