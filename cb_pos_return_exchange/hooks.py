# -*- coding: utf-8 -*-

def post_init_hook(env):
    """Link existing POS configurations to return settings + voucher method."""
    configs = env["pos.config"].search([])
    configs._cb_ensure_return_settings()
    configs._cb_ensure_voucher_payment_method()
