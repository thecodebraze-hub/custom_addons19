# -*- coding: utf-8 -*-
"""Return validation and original order / invoice linking."""

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare


class CbPosReturnValidation(models.Model):
    _inherit = "cb.pos.return"

    original_invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Original Invoice",
        compute="_compute_original_invoice_id",
        store=True,
        index=True,
        check_company=True,
        help="Customer invoice linked to the original POS order.",
    )
    audit_ids = fields.One2many(
        comodel_name="cb.pos.return.audit",
        inverse_name="return_id",
        string="Audit Trail",
        copy=False,
    )
    @api.depends("original_order_id", "original_order_id.account_move")
    def _compute_original_invoice_id(self):
        for record in self:
            order = record.original_order_id
            record.original_invoice_id = order.account_move if order else False

    @api.onchange("original_order_id")
    def _onchange_original_order_id(self):
        if not self.original_order_id:
            return
        order = self.original_order_id
        self.partner_id = order.partner_id
        self.currency_id = order.currency_id
        self.original_payment_ids = order.payment_ids

    def _get_return_config(self):
        self.ensure_one()
        return self.env["cb.pos.return.config"]._get_config(
            company=self.company_id,
            config=self.config_id,
        )

    def _link_original_order(self):
        """Populate partner, payments, and invoice from the original POS order."""
        for record in self:
            order = record.original_order_id
            if not order:
                continue
            vals = {}
            if order.partner_id and record.partner_id != order.partner_id:
                vals["partner_id"] = order.partner_id.id
            payment_ids = order.payment_ids.ids
            if payment_ids and set(record.original_payment_ids.ids) != set(payment_ids):
                vals["original_payment_ids"] = [(6, 0, payment_ids)]
            if vals:
                record.write(vals)
            record.env["cb.pos.return.audit"]._log_event(
                "order_linked",
                message=record.env._(
                    "Linked original POS order %(order)s to return %(return_ref)s.",
                    order=order.display_name,
                    return_ref=record.name,
                ),
                company=record.company_id,
                config=record.config_id,
                session=record.session_id,
                return_id=record,
                pos_order=order,
            )
            if order.account_move:
                record.env["cb.pos.return.audit"]._log_event(
                    "invoice_linked",
                    message=record.env._(
                        "Linked original invoice %(invoice)s.",
                        invoice=order.account_move.display_name,
                    ),
                    company=record.company_id,
                    config=record.config_id,
                    session=record.session_id,
                    return_id=record,
                    pos_order=order,
                    invoice=order.account_move,
                )

    def _validate_return(self, manager_override=False):
        """
        Run all business validations for a return document.

        :param manager_override: skip refund window check when a manager approved.
        :raises UserError / ValidationError: when validation fails.
        """
        self.ensure_one()
        errors = []
        settings = self._get_return_config()

        if not self.line_ids:
            errors.append(self.env._("Add at least one return line."))

        order = self.original_order_id
        if not order:
            errors.append(self.env._("An original POS order is required."))
        elif order.state not in ("paid", "done", "invoiced"):
            errors.append(
                self.env._(
                    "Original order %(name)s must be paid or posted.",
                    name=order.display_name,
                )
            )
        elif order.is_refund:
            errors.append(self.env._("Cannot return against a refund order."))

        if order and order.company_id != self.company_id:
            errors.append(
                self.env._("Original order must belong to the same company.")
            )

        if settings and settings.require_receipt and not self.has_receipt:
            errors.append(self.env._("A sales receipt is required for this return."))

        if settings and settings.require_original_invoice and not self.original_invoice_id:
            errors.append(
                self.env._("The original sale must have a posted customer invoice.")
            )

        if (
            settings
            and settings.max_refund_days
            and not manager_override
            and self.days_since_sale > settings.max_refund_days
        ):
            errors.append(
                self.env._(
                    "Return is outside the maximum refund window of %(days)s days.",
                    days=settings.max_refund_days,
                )
            )

        if self.refund_method == "cash":
            if settings and not settings.allow_cash_refund:
                errors.append(self.env._("Cash refunds are disabled."))
            if not self.env.user.has_group(
                "cb_pos_return_exchange.group_cb_pos_cash_refund"
            ):
                raise AccessError(
                    self.env._("You are not allowed to process cash refunds.")
                )

        for line in self.line_ids:
            line._validate_line_qty()
            if line.original_line_id.order_id != order:
                errors.append(
                    self.env._(
                        "Line %(product)s does not belong to the original order.",
                        product=line.product_id.display_name,
                    )
                )

        if errors:
            message = "\n".join(errors)
            self.env["cb.pos.return.audit"]._log_event(
                "validation_failure",
                message=message,
                success=False,
                company=self.company_id,
                config=self.config_id,
                session=self.session_id,
                return_id=self,
                pos_order=order,
                payload={"errors": errors},
            )
            raise ValidationError(message)

        self.env["cb.pos.return.audit"]._log_event(
            "return_validated",
            message=self.env._("Return %(name)s passed validation.", name=self.name),
            amount=self.amount_total,
            company=self.company_id,
            config=self.config_id,
            session=self.session_id,
            return_id=self,
            pos_order=order,
            invoice=self.original_invoice_id,
        )
        return True

    @api.model
    def _get_returnable_qty(self, order_line):
        """Return remaining returnable quantity for a POS order line."""
        if not order_line:
            return 0.0
        returned_qty = self.env["cb.pos.return.line"]._get_cumulative_returned_qty(
            order_line.id
        )
        precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        remaining = abs(order_line.qty) - returned_qty
        return remaining if float_compare(remaining, 0.0, precision_digits=precision) > 0 else 0.0

    @api.model
    def pos_lookup_order(self, order_ref, config_id):
        """POS RPC: locate an original order (delegates to unified API)."""
        result = self.env["cb.pos.return.api"].pos_find_order(
            config_id, False, order_ref
        )
        if not result.get("success"):
            raise UserError(result.get("error") or self.env._("POS order not found."))
        return result.get("order")
