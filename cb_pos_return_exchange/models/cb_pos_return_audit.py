# -*- coding: utf-8 -*-
"""Structured audit trail for return and exchange events."""

import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CbPosReturnAudit(models.Model):
    """Immutable audit log for return, voucher, and exchange workflow events."""

    _name = "cb.pos.return.audit"
    _description = "POS Return Audit"
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(default="New", readonly=True, index=True)
    event_type = fields.Selection(
        selection=[
            ("order_linked", "Original Order Linked"),
            ("invoice_linked", "Original Invoice Linked"),
            ("validation_failure", "Validation Failure"),
            ("return_validated", "Return Validated"),
            ("return_confirmed", "Return Confirmed"),
            ("return_done", "Return Completed"),
            ("return_cancelled", "Return Cancelled"),
            ("voucher_issued", "Voucher Issued"),
            ("voucher_redeemed", "Voucher Redeemed"),
            ("voucher_partial_redeemed", "Voucher Partially Redeemed"),
            ("voucher_remainder_created", "Remainder Voucher Created"),
            ("voucher_expired", "Voucher Expired"),
            ("voucher_cancelled", "Voucher Cancelled"),
            ("voucher_printed", "Voucher Printed"),
            ("exchange_created", "Exchange Created"),
            ("exchange_completed", "Exchange Completed"),
            ("exchange_cancelled", "Exchange Cancelled"),
            ("stock_picking_created", "Stock Picking Created"),
            ("stock_picking_validated", "Stock Picking Validated"),
            ("stock_validation_failure", "Stock Validation Failure"),
            ("accounting_validation_failure", "Accounting Validation Failure"),
            ("accounting_skipped", "Accounting Skipped"),
            ("credit_note_created", "Credit Note Created"),
            ("credit_note_posted", "Credit Note Posted"),
        ],
        required=True,
        index=True,
    )
    message = fields.Text()
    success = fields.Boolean(default=True, index=True)
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    config_id = fields.Many2one(
        comodel_name="pos.config",
        string="POS Configuration",
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
        string="User",
        default=lambda self: self.env.user,
        index=True,
    )
    return_id = fields.Many2one(
        comodel_name="cb.pos.return",
        string="Return",
        index=True,
        ondelete="set null",
    )
    voucher_id = fields.Many2one(
        comodel_name="cb.pos.return.voucher",
        string="Voucher",
        index=True,
        ondelete="set null",
    )
    exchange_id = fields.Many2one(
        comodel_name="cb.pos.exchange",
        string="Exchange",
        index=True,
        ondelete="set null",
    )
    pos_order_id = fields.Many2one(
        comodel_name="pos.order",
        string="POS Order",
        index=True,
        check_company=True,
    )
    invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        index=True,
        check_company=True,
    )
    payload = fields.Text(help="JSON snapshot of the event context.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = fields.Datetime.now().strftime("RAUD/%Y%m%d/%H%M%S/%f")
        records = super().create(vals_list)
        for audit in records:
            _logger.info(
                "Return audit %s event=%s success=%s",
                audit.name,
                audit.event_type,
                audit.success,
            )
        return records

    @api.model
    def _log_event(
        self,
        event_type,
        *,
        message="",
        success=True,
        amount=0.0,
        company=None,
        config=None,
        session=None,
        return_id=None,
        voucher=None,
        exchange=None,
        pos_order=None,
        invoice=None,
        payload=None,
    ):
        """Create an audit entry when audit logging is enabled."""
        company = company or self.env.company
        settings = self.env["cb.pos.return.config"]._get_config(
            company=company, config=config
        )
        if settings and not settings.enable_audit_log:
            return self.browse()

        payload_text = ""
        if payload is not None:
            try:
                payload_text = json.dumps(payload, default=str)
            except (TypeError, ValueError):
                payload_text = str(payload)

        currency = company.currency_id
        return self.sudo().create(
            {
                "event_type": event_type,
                "message": message,
                "success": success,
                "amount": amount,
                "currency_id": currency.id,
                "company_id": company.id,
                "config_id": config.id if config else False,
                "session_id": session.id if session else False,
                "user_id": self.env.user.id,
                "return_id": return_id.id if return_id else False,
                "voucher_id": voucher.id if voucher else False,
                "exchange_id": exchange.id if exchange else False,
                "pos_order_id": pos_order.id if pos_order else False,
                "invoice_id": invoice.id if invoice else False,
                "payload": payload_text,
            }
        )
