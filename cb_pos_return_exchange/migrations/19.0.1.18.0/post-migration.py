# -*- coding: utf-8 -*-
"""Ensure the dedicated return-voucher payment method exists after upgrade."""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env["pos.config"].search([])
    configs._cb_ensure_voucher_payment_method()
