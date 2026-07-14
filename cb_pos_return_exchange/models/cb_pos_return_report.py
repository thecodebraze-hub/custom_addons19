# -*- coding: utf-8 -*-
"""Reporting helpers on return, voucher, and exchange documents."""

from odoo import api, fields, models


class CbPosReturnReport(models.Model):
    _inherit = "cb.pos.return"

    return_date = fields.Date(
        string="Return Date",
        compute="_compute_return_date",
        store=True,
        index=True,
    )
    original_order_ref = fields.Char(
        string="Original Receipt",
        related="original_order_id.pos_reference",
        store=True,
    )
    report_count = fields.Integer(
        string="Count",
        default=1,
        store=True,
    )

    @api.depends("create_date")
    def _compute_return_date(self):
        for record in self:
            if record.create_date:
                local_dt = fields.Datetime.context_timestamp(record, record.create_date)
                record.return_date = local_dt.date()
            else:
                record.return_date = False


class CbPosReturnVoucherReport(models.Model):
    _inherit = "cb.pos.return.voucher"

    voucher_date = fields.Date(
        string="Voucher Date",
        compute="_compute_voucher_date",
        store=True,
        index=True,
    )
    report_count = fields.Integer(
        string="Count",
        default=1,
        store=True,
    )

    @api.depends("issue_date", "create_date")
    def _compute_voucher_date(self):
        for record in self:
            source = record.issue_date or record.create_date
            if source:
                local_dt = fields.Datetime.context_timestamp(record, source)
                record.voucher_date = local_dt.date()
            else:
                record.voucher_date = False


class CbPosExchangeReport(models.Model):
    _inherit = "cb.pos.exchange"

    exchange_date = fields.Date(
        string="Exchange Date",
        compute="_compute_exchange_date",
        store=True,
        index=True,
    )
    report_count = fields.Integer(
        string="Count",
        default=1,
        store=True,
    )

    @api.depends("create_date")
    def _compute_exchange_date(self):
        for record in self:
            if record.create_date:
                local_dt = fields.Datetime.context_timestamp(record, record.create_date)
                record.exchange_date = local_dt.date()
            else:
                record.exchange_date = False
