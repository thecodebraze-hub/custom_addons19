# -*- coding: utf-8 -*-
"""Credit note line preparation from return lines."""

from odoo import models
from odoo.exceptions import UserError


class CbPosReturnLineAccounting(models.Model):
    _inherit = "cb.pos.return.line"

    def _prepare_credit_note_base_line_values(self):
        """Build tax base line values mirroring POS order line accounting."""
        self.ensure_one()
        ret = self.return_id
        order = ret.original_order_id
        commercial_partner = ret.partner_id.commercial_partner_id
        fiscal_position = order.fiscal_position_id
        line = self.with_company(ret.company_id)
        account = line.product_id._get_product_accounts()["income"]
        if not account and line.original_line_id:
            invoice_lines = line.original_line_id.sale_order_line_id.invoice_lines
            if invoice_lines:
                account = invoice_lines[:1].account_id
        if not account and ret.config_id.invoice_journal_id:
            account = ret.config_id.invoice_journal_id.default_account_id
        if not account and ret.config_id.journal_id:
            account = ret.config_id.journal_id.default_account_id
        if not account:
            raise UserError(
                self.env._(
                    "Please define an income account for product '%(product)s'.",
                    product=line.product_id.display_name,
                )
            )
        if fiscal_position:
            account = fiscal_position.map_account(account)

        tax_ids = fiscal_position.map_tax(line.tax_ids) if fiscal_position else line.tax_ids
        lang = ret.partner_id.lang or self.env.user.lang
        product_name = line.product_id.with_context(lang=lang).display_name
        if line.product_id.description_sale:
            product_name += "\n" + line.product_id.with_context(lang=lang).description_sale

        return {
            **self.env["account.tax"]._prepare_base_line_for_taxes_computation(
                line,
                partner_id=commercial_partner,
                currency_id=ret.currency_id,
                rate=order.currency_rate or 1.0,
                product_id=line.product_id,
                tax_ids=tax_ids,
                price_unit=line.price_unit,
                quantity=line.qty,
                discount=line.discount,
                account_id=account,
                is_refund=True,
                sign=1.0,
            ),
            "uom_id": line.uom_id,
            "name": product_name,
        }

    def _prepare_credit_note_invoice_line_vals(self):
        """Convert return line to account.move.line create values."""
        self.ensure_one()
        line_values = self._prepare_credit_note_base_line_values()
        return self.return_id.original_order_id._get_invoice_lines_values(
            line_values,
            self.original_line_id,
            "out_refund",
        )
