# -*- coding: utf-8 -*-
"""Backfill a bank journal on the return-voucher payment method.

Earlier versions created the method journal-less (pay_later / Customer Account
type), which crashed the enterprise ``pos_settle_due`` flow when validating an
order with no customer. Assigning a dedicated bank journal fixes both the crash
and the accounting (redemptions book to a liquidity account, not receivable).
"""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    methods = env["pos.payment.method"].sudo().search(
        [("cb_is_voucher_method", "=", True)]
    )
    for method in methods:
        if not method.journal_id:
            method.journal_id = env["pos.payment.method"]._cb_get_voucher_journal(
                method.company_id
            ).id
    # Ensure every POS still offers the (now bank-backed) method.
    env["pos.config"].search([])._cb_ensure_voucher_payment_method()
