# -*- coding: utf-8 -*-
"""Return and exchange configuration per company / POS."""

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CbPosReturnConfig(models.Model):
    """Configuration for POS return, voucher, and exchange policies."""

    _name = "cb.pos.return.config"
    _description = "POS Return Configuration"
    _order = "company_id, config_id"
    _check_company_auto = True

    name = fields.Char(required=True, default="Return & Exchange Settings")
    active = fields.Boolean(default=True)
    module_enabled = fields.Boolean(
        string="Enable Module",
        default=True,
        help="Enable return, exchange, and voucher features for this company or POS.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    config_id = fields.Many2one(
        comodel_name="pos.config",
        string="POS Configuration Override",
        check_company=True,
        index=True,
        help="Leave empty for company-wide defaults.",
    )
    max_refund_days = fields.Integer(
        string="Maximum Refund Days",
        default=30,
        help="Maximum days after the original sale to accept a return without override.",
    )
    voucher_validity_days = fields.Integer(
        string="Voucher Expiry Days",
        default=365,
        help="Number of days before an issued voucher expires.",
    )
    require_receipt = fields.Boolean(
        string="Require Original Receipt",
        default=False,
        help="Customers must present the original sale receipt to process a return.",
    )
    allow_cash_refund = fields.Boolean(
        string="Allow Cash Refund",
        default=True,
    )
    allow_partial_voucher_redemption = fields.Boolean(
        string="Allow Partial Voucher",
        default=True,
        help="Allow redeeming only part of a voucher balance on a POS order.",
    )
    allow_multiple_voucher_usage = fields.Boolean(
        string="Allow Multiple Voucher Usage",
        default=True,
        help="Allow applying more than one voucher on the same POS order.",
    )
    auto_print_voucher = fields.Boolean(
        string="Automatic Voucher Printing",
        default=False,
        help="Automatically print the voucher receipt when a voucher is issued.",
    )
    issue_remainder_voucher = fields.Boolean(
        string="Issue Remainder Voucher on Partial Redemption",
        default=False,
        help="Create a new voucher for the unused balance after partial redemption.",
    )
    require_original_invoice = fields.Boolean(
        string="Require Original Invoice",
        default=False,
        help="Reject returns when the original POS order has no posted invoice.",
    )
    enable_audit_log = fields.Boolean(
        string="Enable Audit Log",
        default=True,
    )
    auto_create_credit_note = fields.Boolean(
        string="Auto-Create Credit Notes",
        default=True,
        help="Automatically create a customer credit note when completing a return "
        "against a posted invoice.",
    )
    auto_post_credit_note = fields.Boolean(
        string="Auto-Post Credit Notes",
        default=True,
        help="Automatically post credit notes after creation.",
    )
    quarantine_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Quarantine Location",
        check_company=True,
        domain="[('usage', '=', 'internal')]",
        help="Destination for returned products marked as quarantine.",
    )
    validate_lot_from_sale = fields.Boolean(
        string="Validate Lot/Serial From Original Sale",
        default=True,
        help="Reject returns when the lot/serial was not delivered on the original order.",
    )
    auto_validate_return_picking = fields.Boolean(
        string="Auto-Validate Return Pickings",
        default=True,
        help="Automatically validate stock pickings when a return is confirmed.",
    )
    voucher_barcode_prefix = fields.Char(
        string="Voucher Barcode Prefix",
        default="VCH/",
        help="Prefix used to recognize return voucher barcodes (Code128).",
    )
    voucher_barcode_type = fields.Selection(
        selection=[
            ("code128", "Code 128"),
            ("ean13", "EAN-13"),
            ("ean8", "EAN-8"),
        ],
        string="Barcode Type",
        default="code128",
        required=True,
        help="Linear barcode format printed on voucher receipts.",
    )
    voucher_use_qr_code = fields.Boolean(
        string="QR Code",
        default=False,
        help="Print a QR code on voucher receipts in addition to the linear barcode.",
    )
    return_barcode_prefix = fields.Char(
        string="Return Barcode Prefix",
        default="RET/",
        help="Prefix used to recognize return document barcodes (Code128).",
    )
    auto_barcode_detect = fields.Boolean(
        string="Auto-Detect Return Barcodes",
        default=True,
        help="Automatically classify scanned barcodes as product, voucher, or return.",
    )
    receipt_paper_width = fields.Selection(
        selection=[
            ("58", "58 mm"),
            ("80", "80 mm"),
        ],
        string="Default Receipt Width",
        default="80",
        help="Default thermal paper width for return, voucher, and exchange receipts.",
    )
    receipt_thank_you_message = fields.Char(
        string="Receipt Thank You Message",
        default="Thank you for shopping with us!",
        translate=True,
    )
    receipt_header_message = fields.Char(
        string="Receipt Header Message",
        translate=True,
        help="Optional message printed below the company logo on receipts.",
    )

    _company_config_uniq = models.Constraint(
        "UNIQUE(company_id, config_id)",
        "Only one configuration is allowed per company and POS configuration.",
    )

    _SETTINGS_COPY_FIELDS = (
        "module_enabled",
        "max_refund_days",
        "voucher_validity_days",
        "require_receipt",
        "allow_cash_refund",
        "allow_partial_voucher_redemption",
        "allow_multiple_voucher_usage",
        "auto_print_voucher",
        "issue_remainder_voucher",
        "require_original_invoice",
        "enable_audit_log",
        "auto_create_credit_note",
        "auto_post_credit_note",
        "validate_lot_from_sale",
        "auto_validate_return_picking",
        "voucher_barcode_prefix",
        "voucher_barcode_type",
        "voucher_use_qr_code",
        "return_barcode_prefix",
        "auto_barcode_detect",
        "receipt_paper_width",
        "receipt_thank_you_message",
        "receipt_header_message",
    )

    def _copy_settings_values(self):
        """Return a dict of settings values suitable for create/write."""
        self.ensure_one()
        return {field: self[field] for field in self._SETTINGS_COPY_FIELDS}

    @api.model
    def _settings_payload(self, settings):
        """Serialize resolved settings for the POS client."""
        if not settings:
            return {
                "module_enabled": True,
                "max_refund_days": 30,
                "voucher_validity_days": 365,
                "voucher_expiry_days": 365,
                "require_receipt": False,
                "allow_cash_refund": True,
                "allow_partial_voucher_redemption": True,
                "allow_partial_voucher": True,
                "allow_multiple_voucher_usage": True,
                "auto_print_voucher": False,
                "require_original_invoice": False,
                "auto_create_credit_note": True,
                "validate_lot_from_sale": True,
                "voucher_barcode_prefix": "VCH/",
                "voucher_barcode_type": "code128",
                "voucher_use_qr_code": False,
                "return_barcode_prefix": "RET/",
                "auto_barcode_detect": True,
            }
        return {
            "module_enabled": settings.module_enabled,
            "max_refund_days": settings.max_refund_days,
            "voucher_validity_days": settings.voucher_validity_days,
            "voucher_expiry_days": settings.voucher_validity_days,
            "require_receipt": settings.require_receipt,
            "allow_cash_refund": settings.allow_cash_refund,
            "allow_partial_voucher_redemption": settings.allow_partial_voucher_redemption,
            "allow_partial_voucher": settings.allow_partial_voucher_redemption,
            "allow_multiple_voucher_usage": settings.allow_multiple_voucher_usage,
            "auto_print_voucher": settings.auto_print_voucher,
            "require_original_invoice": settings.require_original_invoice,
            "auto_create_credit_note": settings.auto_create_credit_note,
            "validate_lot_from_sale": settings.validate_lot_from_sale,
            "voucher_barcode_prefix": settings.voucher_barcode_prefix,
            "voucher_barcode_type": settings.voucher_barcode_type,
            "voucher_use_qr_code": settings.voucher_use_qr_code,
            "return_barcode_prefix": settings.return_barcode_prefix,
            "auto_barcode_detect": settings.auto_barcode_detect,
        }

    @api.constrains("max_refund_days", "voucher_validity_days")
    def _check_positive_values(self):
        for config in self:
            if config.max_refund_days < 0:
                raise ValidationError(self.env._("Maximum refund days cannot be negative."))
            if config.voucher_validity_days <= 0:
                raise ValidationError(self.env._("Voucher validity must be positive."))

    @api.model
    def _get_config(self, company=None, config=None):
        """Resolve the most specific active configuration record."""
        company = company or self.env.company
        domain = [("active", "=", True), ("company_id", "=", company.id)]
        if config:
            specific = self.search(domain + [("config_id", "=", config.id)], limit=1)
            if specific:
                return specific
        return self.search(domain + [("config_id", "=", False)], limit=1)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group(
            "cb_pos_return_exchange.group_cb_pos_modify_settings"
        ):
            raise AccessError(
                self.env._("You are not allowed to modify return and exchange settings.")
            )
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group(
            "cb_pos_return_exchange.group_cb_pos_modify_settings"
        ):
            raise AccessError(
                self.env._("You are not allowed to modify return and exchange settings.")
            )
        return super().create(vals_list)
