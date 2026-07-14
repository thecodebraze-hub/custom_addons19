# -*- coding: utf-8 -*-
"""Credit note generation and accounting integrity for POS returns."""

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CbPosReturnAccounting(models.Model):
    _inherit = "cb.pos.return"

    credit_note_id = fields.Many2one(
        comodel_name="account.move",
        string="Credit Note",
        related="account_move_id",
        readonly=True,
    )
    accounting_state = fields.Selection(
        selection=[
            ("none", "Not Applicable"),
            ("pending", "Pending"),
            ("posted", "Posted"),
            ("skipped", "Skipped"),
            ("error", "Error"),
        ],
        string="Accounting Status",
        default="none",
        copy=False,
        index=True,
        tracking=True,
    )

    def _get_accounting_config(self):
        self.ensure_one()
        return self._get_return_config()

    def _should_create_credit_note(self):
        """Credit notes are created only against posted original invoices."""
        self.ensure_one()
        settings = self._get_accounting_config()
        if settings and not settings.auto_create_credit_note:
            return False
        invoice = self.original_invoice_id
        return bool(
            invoice
            and invoice.state == "posted"
            and invoice.move_type == "out_invoice"
        )

    def _validate_accounting(self):
        """Validate accounting preconditions without modifying posted invoices."""
        self.ensure_one()
        if not self._should_create_credit_note():
            return True

        errors = []
        invoice = self.original_invoice_id
        if not invoice or invoice.state != "posted":
            errors.append(
                self.env._("A posted customer invoice is required to create a credit note.")
            )
        if invoice and invoice.company_id != self.company_id:
            errors.append(
                self.env._("Original invoice must belong to the same company as the return.")
            )

        lock_date = self.company_id._get_user_fiscal_lock_date(
            invoice.journal_id if invoice else False
        )
        if lock_date and fields.Date.today() <= lock_date:
            errors.append(
                self.env._(
                    "Credit note date falls inside the fiscal lock period (%(date)s).",
                    date=lock_date,
                )
            )

        for line in self.line_ids:
            if not line.product_id or line.product_id.type == "combo":
                continue
            invoice_lines = invoice.invoice_line_ids.filtered(
                lambda aml: aml.product_id == line.product_id and aml.display_type == "product"
            )
            if not invoice_lines and line.product_id:
                errors.append(
                    self.env._(
                        "Product %(product)s was not found on the original invoice.",
                        product=line.product_id.display_name,
                    )
                )

        if errors:
            self.env["cb.pos.return.audit"]._log_event(
                "accounting_validation_failure",
                message="\n".join(errors),
                success=False,
                company=self.company_id,
                config=self.config_id,
                session=self.session_id,
                return_id=self,
                invoice=invoice,
                payload={"errors": errors},
            )
            raise ValidationError("\n".join(errors))
        return True

    def _prepare_credit_note_vals(self):
        """Prepare account.move values for an out_refund credit note."""
        self.ensure_one()
        original_invoice = self.original_invoice_id
        order = self.original_order_id
        fiscal_position = order.fiscal_position_id
        journal = (
            self.config_id.invoice_journal_id
            or original_invoice.journal_id
        )
        partner = self.partner_id or order.partner_id
        invoice_lines = []
        for line in self.line_ids:
            if line.product_id.type == "combo":
                continue
            invoice_lines.append(
                Command.create(line._prepare_credit_note_invoice_line_vals())
            )

        if not invoice_lines:
            raise UserError(
                self.env._("No invoice lines could be prepared for credit note creation.")
            )

        return {
            "move_type": "out_refund",
            "reversed_entry_id": original_invoice.id,
            "cb_original_invoice_id": original_invoice.id,
            "cb_pos_return_id": self.id,
            "cb_pos_return_voucher_id": self.voucher_id.id if self.voucher_id else False,
            "partner_id": partner.address_get(["invoice"])["invoice"],
            "partner_shipping_id": partner.address_get(["delivery"])["delivery"],
            "journal_id": journal.id,
            "currency_id": self.currency_id.id,
            "invoice_date": fields.Date.context_today(self),
            "fiscal_position_id": fiscal_position.id if fiscal_position else False,
            "invoice_origin": self.name,
            "invoice_user_id": self.cashier_id.id or self.env.user.id,
            "ref": self.env._(
                "Credit note for return %(return_ref)s (reversal of %(invoice)s)",
                return_ref=self.name,
                invoice=original_invoice.name,
            ),
            "invoice_line_ids": invoice_lines,
            "narration": self.note,
        }

    def _create_credit_note(self):
        """
        Create and post a customer credit note linked to the original invoice.

        Posted invoices are never modified; a new out_refund move is created.
        """
        self.ensure_one()
        if self.account_move_id:
            return self.account_move_id

        if not self._should_create_credit_note():
            self.accounting_state = "skipped"
            self.env["cb.pos.return.audit"]._log_event(
                "accounting_skipped",
                message=self.env._(
                    "Credit note skipped: no posted original invoice or setting disabled."
                ),
                company=self.company_id,
                config=self.config_id,
                session=self.session_id,
                return_id=self,
                pos_order=self.original_order_id,
            )
            return self.env["account.move"]

        self._validate_accounting()
        self.accounting_state = "pending"

        move_vals = self._prepare_credit_note_vals()
        if self.voucher_id:
            move_vals["cb_pos_return_voucher_id"] = self.voucher_id.id

        credit_note = (
            self.env["account.move"]
            .sudo()
            .with_company(self.company_id)
            .with_context(default_move_type="out_refund", linked_to_pos=True)
            .create(move_vals)
        )

        settings = self._get_accounting_config()
        if not settings or settings.auto_post_credit_note:
            credit_note.with_context(skip_invoice_sync=True).action_post()

        self.write({
            "account_move_id": credit_note.id,
            "accounting_state": "posted" if credit_note.state == "posted" else "pending",
        })

        if self.voucher_id and not credit_note.cb_pos_return_voucher_id:
            credit_note.cb_pos_return_voucher_id = self.voucher_id.id

        credit_note.message_post(
            body=self.env._(
                "Credit note created from POS return %(return_ref)s. "
                "Original invoice: %(invoice)s.",
                return_ref=self.name,
                invoice=self.original_invoice_id.name,
            )
        )

        original_invoice = self.original_invoice_id
        self.env["cb.pos.return.audit"]._log_event(
            "credit_note_created",
            message=self.env._(
                "Credit note %(credit)s created for return %(return_ref)s.",
                credit=credit_note.name,
                return_ref=self.name,
            ),
            amount=credit_note.amount_total,
            company=self.company_id,
            config=self.config_id,
            session=self.session_id,
            return_id=self,
            voucher=self.voucher_id,
            pos_order=self.original_order_id,
            invoice=original_invoice,
            payload={
                "credit_note_id": credit_note.id,
                "original_invoice_id": original_invoice.id,
            },
        )

        if credit_note.state == "posted":
            self.env["cb.pos.return.audit"]._log_event(
                "credit_note_posted",
                message=self.env._(
                    "Credit note %(credit)s posted.",
                    credit=credit_note.name,
                ),
                amount=credit_note.amount_total,
                company=self.company_id,
                config=self.config_id,
                session=self.session_id,
                return_id=self,
                voucher=self.voucher_id,
                invoice=credit_note,
            )
        return credit_note

    def _cancel_credit_note(self):
        """Cancel draft credit notes; block if already posted."""
        for record in self:
            move = record.account_move_id
            if not move:
                continue
            if move.state == "posted":
                raise UserError(
                    record.env._(
                        "Cannot cancel return %(name)s: credit note %(credit)s is already posted.",
                        name=record.name,
                        credit=move.name,
                    )
                )
            if move.state == "draft":
                move.button_cancel()
            record.write({
                "account_move_id": False,
                "accounting_state": "none",
            })

    def action_view_credit_note(self):
        self.ensure_one()
        if not self.account_move_id:
            raise UserError(self.env._("No credit note is linked to this return."))
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Credit Note"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.account_move_id.id,
            "context": {"default_move_type": "out_refund"},
        }
