# -*- coding: utf-8 -*-
"""Shared helpers for POS thermal receipt reports."""

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools.misc import format_datetime, formatLang


class CbPosReturnReceiptMixin(models.AbstractModel):
    """Mixin providing receipt context for return, voucher, and exchange documents."""

    _name = "cb.pos.return.receipt.mixin"
    _description = "POS Return Receipt Mixin"

    @api.model
    def _cb_receipt_settings(self, company, config=None):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=company, config=config
        )
        thank_you = (
            settings.receipt_thank_you_message
            if settings and settings.receipt_thank_you_message
            else self.env._("Thank you for shopping with us!")
        )
        header = settings.receipt_header_message if settings else ""
        return {
            "thank_you_message": thank_you,
            "header_message": header,
            "paper_width": settings.receipt_paper_width if settings else "80",
            "voucher_barcode_type": settings.voucher_barcode_type if settings else "code128",
            "voucher_use_qr_code": settings.voucher_use_qr_code if settings else False,
        }

    def _cb_receipt_barcode_value(self):
        self.ensure_one()
        return self.name or ""

    def _cb_receipt_barcode_type(self, value, settings=None):
        if settings and settings.get("voucher_barcode_type"):
            type_map = {
                "code128": "Code128",
                "ean13": "EAN13",
                "ean8": "EAN8",
            }
            return type_map.get(settings["voucher_barcode_type"], "Code128")
        digits = "".join(ch for ch in (value or "") if ch.isdigit())
        if value and digits == value and len(digits) in (8, 12, 13):
            return "EAN13" if len(digits) in (12, 13) else "EAN8"
        return "Code128"

    def _cb_format_receipt_datetime(self, dt):
        if not dt:
            return ""
        return format_datetime(self.env, dt)

    def _cb_format_receipt_amount(self, amount):
        self.ensure_one()
        currency = getattr(self, "currency_id", False) or self.company_id.currency_id
        return formatLang(self.env, amount, currency_obj=currency)

    def _cb_action_print_receipt(self, receipt_type):
        self.ensure_one()
        config = getattr(self, "config_id", False)
        settings = self._cb_receipt_settings(self.company_id, config)
        width = settings.get("paper_width") or "80"
        report = self.env.ref(
            f"cb_pos_return_exchange.action_report_cb_{receipt_type}_receipt_{width}",
            raise_if_not_found=False,
        )
        if not report:
            report = self.env.ref(
                f"cb_pos_return_exchange.action_report_cb_{receipt_type}_receipt_80"
            )
        return report.report_action(self)


class CbPosReturn(models.Model):
    _name = "cb.pos.return"
    _inherit = ["cb.pos.return", "cb.pos.return.receipt.mixin"]

    def _cb_receipt_barcode_value(self):
        self.ensure_one()
        # Print the redeemable voucher barcode so the customer can scan it at
        # the payment screen. Fall back to the return reference otherwise.
        voucher = self.voucher_id or self.voucher_ids[:1]
        if voucher and voucher.barcode:
            return voucher.barcode
        return self.name or ""

    def action_print_return_receipt(self):
        return self._cb_action_print_receipt("return")

    def pos_get_return_receipt_data(self):
        """Return receipt payload for POS thermal printing (no PDF)."""
        self.ensure_one()
        settings = self._cb_receipt_settings(self.company_id, self.config_id)
        barcode_value = self._cb_receipt_barcode_value()
        barcode_type = self._cb_receipt_barcode_type(barcode_value, settings)
        width = int(settings.get("paper_width") or 80)
        barcode_width = 220 if width == 58 else 300
        refund_labels = dict(self._fields["refund_method"].selection)
        voucher = self.voucher_id or self.voucher_ids[:1]
        company = self.company_id

        from urllib.parse import quote

        encoded_barcode = quote(barcode_value or "", safe="")
        barcode_url = (
            f"/report/barcode/{barcode_type}/{encoded_barcode}"
            f"?width={barcode_width}&height=70&humanreadable=1"
        )
        qr_url = False
        if settings.get("voucher_use_qr_code") and barcode_value:
            qr_size = 120 if width == 58 else 150
            qr_url = (
                f"/report/barcode/QR/{encoded_barcode}"
                f"?width={qr_size}&height={qr_size}"
            )

        return {
            "title": self.env._("RETURN RECEIPT"),
            "name": self.name,
            "date": self._cb_format_receipt_datetime(self.create_date),
            "cashier_name": self.cashier_id.name if self.cashier_id else "",
            "partner_name": self.partner_id.name if self.partner_id else "",
            "original_order_name": (
                self.original_order_id.pos_reference or self.original_order_id.name
                if self.original_order_id
                else ""
            ),
            "refund_method": refund_labels.get(self.refund_method, self.refund_method),
            "reason": self.reason or "",
            "lines": [
                {
                    "product_name": line.product_id.display_name,
                    "qty": line.qty,
                    "price_total": self._cb_format_receipt_amount(line.price_total),
                }
                for line in self.line_ids
            ],
            "amount_untaxed": self._cb_format_receipt_amount(self.amount_untaxed),
            "amount_tax": self._cb_format_receipt_amount(self.amount_tax),
            "amount_total": self._cb_format_receipt_amount(self.amount_total),
            "voucher_name": voucher.name if voucher else "",
            "voucher_remaining": (
                self._cb_format_receipt_amount(voucher.amount_remaining) if voucher else ""
            ),
            "barcode_value": barcode_value,
            "barcode_url": barcode_url,
            "qr_url": qr_url,
            "company_name": company.name,
            "company_phone": company.phone or "",
            "company_email": company.email or "",
            "company_website": company.website or "",
            "company_vat": company.vat or "",
            "header_message": settings.get("header_message") or "",
            "thank_you_message": settings.get("thank_you_message") or "",
            "paper_width": width,
        }


class CbPosReturnVoucher(models.Model):
    _name = "cb.pos.return.voucher"
    _inherit = ["cb.pos.return.voucher", "cb.pos.return.receipt.mixin"]

    def _cb_receipt_barcode_value(self):
        self.ensure_one()
        return self.barcode or self.name or ""

    def _cb_receipt_customer_balance(self):
        self.ensure_one()
        if not self.partner_id:
            return 0.0
        vouchers = self.env["cb.pos.return.voucher"].search(
            [
                ("partner_id", "=", self.partner_id.id),
                ("company_id", "=", self.company_id.id),
                ("state", "in", ("issued", "partial")),
            ]
        )
        return sum(vouchers.mapped("amount_remaining"))

    def action_print_voucher_receipt(self):
        self.ensure_one()
        if not self.env.user.has_group(
            "cb_pos_return_exchange.group_cb_pos_print_voucher"
        ):
            raise AccessError(self.env._("You are not allowed to print vouchers."))
        self.write(
            {
                "print_count": self.print_count + 1,
                "last_printed": fields.Datetime.now(),
                "printed_by": self.env.user.id,
            }
        )
        self.env["cb.pos.return.audit"]._log_event(
            "voucher_printed",
            message=self.env._(
                "Voucher %(name)s receipt printed (count=%(count)s).",
                name=self.name,
                count=self.print_count,
            ),
            company=self.company_id,
            config=self.config_id,
            return_id=self.return_id,
            voucher=self,
        )
        return self._cb_action_print_receipt("voucher")

    def pos_get_voucher_receipt_data(self):
        """Voucher receipt payload for POS thermal printing (no PDF).

        Mirrors ``pos_get_return_receipt_data`` so the voucher can be printed
        on the POS thermal printer without wkhtmltopdf.
        """
        self.ensure_one()
        settings = self._cb_receipt_settings(self.company_id, self.config_id)
        barcode_value = self._cb_receipt_barcode_value()
        barcode_type = self._cb_receipt_barcode_type(barcode_value, settings)
        width = int(settings.get("paper_width") or 80)
        barcode_width = 220 if width == 58 else 300
        company = self.company_id

        from urllib.parse import quote

        encoded_barcode = quote(barcode_value or "", safe="")
        barcode_url = (
            f"/report/barcode/{barcode_type}/{encoded_barcode}"
            f"?width={barcode_width}&height=70&humanreadable=1"
        )
        qr_url = False
        if settings.get("voucher_use_qr_code") and barcode_value:
            qr_size = 120 if width == 58 else 150
            qr_url = (
                f"/report/barcode/QR/{encoded_barcode}"
                f"?width={qr_size}&height={qr_size}"
            )

        return {
            "title": self.env._("EXCHANGE VOUCHER"),
            "name": self.name,
            "date": self._cb_format_receipt_datetime(self.issue_date or self.create_date),
            "partner_name": self.partner_id.name if self.partner_id else "",
            "amount": self._cb_format_receipt_amount(self.amount),
            "amount_remaining": self._cb_format_receipt_amount(self.amount_remaining),
            "expiry_date": self._cb_format_receipt_datetime(self.expiry_date),
            "note": self.note or "",
            "barcode_value": barcode_value,
            "barcode_url": barcode_url,
            "qr_url": qr_url,
            "company_name": company.name,
            "company_phone": company.phone or "",
            "company_vat": company.vat or "",
            "header_message": settings.get("header_message") or "",
            "thank_you_message": settings.get("thank_you_message") or "",
            "paper_width": width,
        }


class CbPosExchange(models.Model):
    _name = "cb.pos.exchange"
    _inherit = ["cb.pos.exchange", "cb.pos.return.receipt.mixin"]

    def _cb_receipt_barcode_value(self):
        self.ensure_one()
        return self.name or ""

    def action_print_exchange_receipt(self):
        return self._cb_action_print_receipt("exchange")
