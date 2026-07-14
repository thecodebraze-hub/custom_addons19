# -*- coding: utf-8 -*-
"""POS configuration integration for return and exchange settings."""

from odoo import api, fields, models


class PosConfigReturnExchange(models.Model):
    _inherit = "pos.config"

    cb_return_settings_id = fields.Many2one(
        comodel_name="cb.pos.return.config",
        string="Return & Exchange Settings",
        copy=False,
        ondelete="restrict",
        groups="cb_pos_return_exchange.group_cb_pos_modify_settings",
    )

    cb_module_enabled = fields.Boolean(
        string="Enable Module",
        related="cb_return_settings_id.module_enabled",
        readonly=False,
    )
    cb_voucher_expiry_days = fields.Integer(
        string="Voucher Expiry Days",
        related="cb_return_settings_id.voucher_validity_days",
        readonly=False,
    )
    cb_allow_cash_refund = fields.Boolean(
        string="Allow Cash Refund",
        related="cb_return_settings_id.allow_cash_refund",
        readonly=False,
    )
    cb_require_receipt = fields.Boolean(
        string="Require Original Receipt",
        related="cb_return_settings_id.require_receipt",
        readonly=False,
    )
    cb_allow_partial_voucher = fields.Boolean(
        string="Allow Partial Voucher",
        related="cb_return_settings_id.allow_partial_voucher_redemption",
        readonly=False,
    )
    cb_allow_multiple_voucher_usage = fields.Boolean(
        string="Allow Multiple Voucher Usage",
        related="cb_return_settings_id.allow_multiple_voucher_usage",
        readonly=False,
    )
    cb_auto_print_voucher = fields.Boolean(
        string="Automatic Voucher Printing",
        related="cb_return_settings_id.auto_print_voucher",
        readonly=False,
    )
    cb_voucher_barcode_type = fields.Selection(
        related="cb_return_settings_id.voucher_barcode_type",
        readonly=False,
    )
    cb_voucher_use_qr_code = fields.Boolean(
        string="QR Code",
        related="cb_return_settings_id.voucher_use_qr_code",
        readonly=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        configs._cb_ensure_return_settings()
        configs._cb_ensure_voucher_payment_method()
        return configs

    def _cb_ensure_voucher_payment_method(self):
        """Ensure each POS offers the dedicated return-voucher payment method."""
        PaymentMethod = self.env["pos.payment.method"].sudo()
        for pos in self.sudo():
            method = PaymentMethod._cb_ensure_voucher_method(pos.company_id)
            if method and method.id not in pos.payment_method_ids.ids:
                # Allow linking even when a session is open; the method simply
                # becomes available the next time the session is opened.
                pos.with_context(
                    bypass_payment_method_ids_forbidden_change=True
                ).write({"payment_method_ids": [(4, method.id)]})

    def _cb_ensure_return_settings(self):
        """Create a POS-specific settings record when missing."""
        ReturnConfig = self.env["cb.pos.return.config"].sudo()
        for pos in self.sudo():
            if pos.cb_return_settings_id:
                continue
            existing = ReturnConfig.search(
                [("company_id", "=", pos.company_id.id), ("config_id", "=", pos.id)],
                limit=1,
            )
            if existing:
                pos.sudo().cb_return_settings_id = existing.id
                continue
            company_defaults = ReturnConfig._get_config(
                company=pos.company_id, config=False
            )
            vals = {
                "name": self.env._("%(pos)s — Return & Exchange", pos=pos.name),
                "company_id": pos.company_id.id,
                "config_id": pos.id,
            }
            if company_defaults:
                vals.update(company_defaults._copy_settings_values())
            settings = ReturnConfig.create(vals)
            pos.sudo().cb_return_settings_id = settings.id

    def get_cb_return_settings(self):
        """Return the resolved settings record for this POS."""
        self.ensure_one()
        if not self.cb_return_settings_id:
            self._cb_ensure_return_settings()
        return self.env["cb.pos.return.config"]._get_config(
            company=self.company_id,
            config=self,
        )
