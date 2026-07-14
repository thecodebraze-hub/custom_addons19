# -*- coding: utf-8 -*-
"""Return workflow actions: confirm, complete, cancel."""

from odoo import api, models
from odoo.exceptions import UserError


class CbPosReturnWorkflow(models.Model):
    _inherit = "cb.pos.return"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._link_original_order()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "original_order_id" in vals:
            self._link_original_order()
        return res

    def action_confirm(self):
        """Validate and move the return to confirmed."""
        for record in self:
            if record.state != "draft":
                raise UserError(
                    record.env._(
                        "Return %(name)s cannot be confirmed from status %(state)s.",
                        name=record.name,
                        state=record.state,
                    )
                )
            record._link_original_order()
            manager_override = bool(record.manager_id)
            record._validate_return(manager_override=manager_override)
            record._validate_stock()
            record._create_return_stock_pickings()
            record.state = "confirmed"
            record.env["cb.pos.return.audit"]._log_event(
                "return_confirmed",
                message=record.env._("Return %(name)s confirmed.", name=record.name),
                amount=record.amount_total,
                company=record.company_id,
                config=record.config_id,
                session=record.session_id,
                return_id=record,
                pos_order=record.original_order_id,
                invoice=record.original_invoice_id,
            )
        return True

    def action_done(self):
        """Complete the return and trigger settlement (voucher / exchange handoff)."""
        for record in self:
            if record.state not in ("draft", "confirmed"):
                raise UserError(
                    record.env._(
                        "Return %(name)s must be draft or confirmed before completion.",
                        name=record.name,
                    )
                )
            if record.state == "draft":
                record.action_confirm()

            # Voucher, store-credit and exchange settlements all hand the
            # customer a redeemable voucher barcode (scanned at payment for the
            # replacement purchase), so issue a voucher for each of them.
            if (
                record.refund_method in ("voucher", "store_credit", "exchange")
                and not record.voucher_id
            ):
                voucher = record.env["cb.pos.return.voucher"]._issue_from_return(record)
                record.voucher_id = voucher.id

            record._create_credit_note()

            record.state = "done"
            record.message_post(
                body=record.env._(
                    "Return completed with refund method %(method)s.",
                    method=dict(record._fields["refund_method"].selection).get(
                        record.refund_method
                    ),
                )
            )
            record.env["cb.pos.return.audit"]._log_event(
                "return_done",
                message=record.env._("Return %(name)s completed.", name=record.name),
                amount=record.amount_total,
                company=record.company_id,
                config=record.config_id,
                session=record.session_id,
                return_id=record,
                voucher=record.voucher_id,
                pos_order=record.original_order_id,
                invoice=record.original_invoice_id,
            )
        return True

    def action_cancel(self):
        """Cancel a return that is not yet completed."""
        for record in self:
            if record.state == "done":
                raise UserError(
                    record.env._("Completed returns cannot be cancelled.")
                )
            if record.state == "confirmed":
                record._cancel_return_stock_pickings()
                record._cancel_credit_note()
            record.state = "cancelled"
            record.env["cb.pos.return.audit"]._log_event(
                "return_cancelled",
                message=record.env._("Return %(name)s cancelled.", name=record.name),
                company=record.company_id,
                config=record.config_id,
                session=record.session_id,
                return_id=record,
            )
        return True

    def action_reset_draft(self):
        for record in self:
            if record.state == "done":
                raise UserError(record.env._("Completed returns cannot be reset."))
            record.state = "draft"
        return True
