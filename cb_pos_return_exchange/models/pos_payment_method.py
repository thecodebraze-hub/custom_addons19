# -*- coding: utf-8 -*-
"""Dedicated POS payment method for return voucher redemption."""

from odoo import api, fields, models

VOUCHER_METHOD_NAME = "Return Voucher"


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    cb_is_voucher_method = fields.Boolean(
        string="Return Voucher Method",
        help="Marks this payment method as the tender used when a return "
        "voucher barcode is redeemed at the payment screen.",
        copy=False,
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if "cb_is_voucher_method" not in fields_list:
            fields_list.append("cb_is_voucher_method")
        return fields_list

    @api.model
    def _cb_get_voucher_journal(self, company):
        """Get (creating if needed) the dedicated bank journal for vouchers.

        A bank journal keeps the payment method out of the ``pay_later`` type
        (which would otherwise require a customer and break the enterprise
        ``pos_settle_due`` flow) and books redemptions to a clean liquidity
        account instead of the customer receivable.
        """
        Journal = self.env["account.journal"].sudo()
        journal = Journal.search(
            [
                ("company_id", "=", company.id),
                ("type", "=", "bank"),
                ("code", "=", "RVCH"),
            ],
            limit=1,
        )
        if journal:
            return journal
        return Journal.create(
            {
                "name": VOUCHER_METHOD_NAME,
                "type": "bank",
                "code": "RVCH",
                "company_id": company.id,
            }
        )

    @api.model
    def _cb_ensure_voucher_method(self, company):
        """Return (creating if needed) the voucher redemption payment method."""
        company = company or self.env.company
        method = self.sudo().search(
            [
                ("cb_is_voucher_method", "=", True),
                ("company_id", "=", company.id),
            ],
            limit=1,
        )
        if method:
            # Backfill a journal if an earlier version created it journal-less
            # (which resolved to the pay_later / Customer Account type).
            if not method.journal_id:
                method.journal_id = self._cb_get_voucher_journal(company).id
            return method
        journal = self._cb_get_voucher_journal(company)
        return self.sudo().create(
            {
                "name": VOUCHER_METHOD_NAME,
                "company_id": company.id,
                "cb_is_voucher_method": True,
                "split_transactions": False,
                "journal_id": journal.id,
                "sequence": 90,
            }
        )
