# -*- coding: utf-8 -*-
"""Exchange validation and completion logic."""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class CbPosExchangeLogic(models.Model):
    _inherit = "cb.pos.exchange"

    audit_ids = fields.One2many(
        comodel_name="cb.pos.return.audit",
        inverse_name="exchange_id",
        string="Audit Trail",
        copy=False,
    )

    def _validate_exchange(self):
        """Validate exchange prerequisites and settlement amounts."""
        self.ensure_one()
        errors = []

        if not self.return_id:
            errors.append(self.env._("An exchange requires a linked return."))
        elif self.return_id.state == "cancelled":
            errors.append(self.env._("The linked return is cancelled."))

        if not self.replacement_order_id:
            errors.append(self.env._("A replacement POS order is required."))
        elif self.replacement_order_id.state not in ("paid", "done", "invoiced"):
            errors.append(
                self.env._("Replacement order must be paid or posted.")
            )

        rounding = self.currency_id.rounding
        diff = self.difference_amount

        if diff > 0 and float_is_zero(self.customer_payment, precision_rounding=rounding):
            errors.append(
                self.env._(
                    "Customer payment of %(amount)s is required.",
                    amount=diff,
                )
            )
        elif diff > 0 and float_compare(
            self.customer_payment, diff, precision_rounding=rounding
        ) < 0:
            errors.append(
                self.env._(
                    "Customer payment %(paid)s is less than required %(required)s.",
                    paid=self.customer_payment,
                    required=diff,
                )
            )

        if errors:
            self.env["cb.pos.return.audit"]._log_event(
                "validation_failure",
                message="\n".join(errors),
                success=False,
                company=self.company_id,
                config=self.config_id,
                session=self.session_id,
                exchange=self,
                return_id=self.return_id,
                payload={"errors": errors},
            )
            raise ValidationError("\n".join(errors))
        return True

    def action_complete(self):
        """Complete the exchange and settle any financial difference."""
        for exchange in self:
            if exchange.state != "draft":
                raise UserError(
                    exchange.env._(
                        "Exchange %(name)s cannot be completed from status %(state)s.",
                        name=exchange.name,
                        state=exchange.state,
                    )
                )

            exchange._validate_exchange()
            return_doc = exchange.return_id

            if return_doc.state in ("draft", "confirmed"):
                return_doc.write({"refund_method": "exchange"})
                if return_doc.state == "draft":
                    return_doc.action_confirm()
                if return_doc.state == "confirmed":
                    return_doc.action_done()

            rounding = exchange.currency_id.rounding
            if (
                exchange.difference_amount < 0
                and float_compare(
                    exchange.difference_amount,
                    0.0,
                    precision_rounding=rounding,
                ) < 0
                and not exchange.voucher_id
            ):
                voucher = exchange.env["cb.pos.return.voucher"]._issue_from_exchange(
                    exchange,
                    abs(exchange.difference_amount),
                )
                exchange.voucher_id = voucher.id

            exchange.state = "done"
            exchange.message_post(
                body=exchange.env._(
                    "Exchange completed. Settlement mode: %(mode)s.",
                    mode=dict(exchange._fields["settlement_mode"].selection).get(
                        exchange.settlement_mode
                    ),
                )
            )
            exchange.env["cb.pos.return.audit"]._log_event(
                "exchange_completed",
                message=exchange.env._(
                    "Exchange %(name)s completed.", name=exchange.name
                ),
                amount=exchange.difference_amount,
                company=exchange.company_id,
                config=exchange.config_id,
                session=exchange.session_id,
                exchange=exchange,
                return_id=return_doc,
                voucher=exchange.voucher_id,
                pos_order=exchange.replacement_order_id,
            )
        return True

    def action_cancel(self):
        for exchange in self:
            if exchange.state == "done":
                raise UserError(
                    exchange.env._("Completed exchanges cannot be cancelled.")
                )
            exchange.state = "cancelled"
            exchange.env["cb.pos.return.audit"]._log_event(
                "exchange_cancelled",
                message=exchange.env._(
                    "Exchange %(name)s cancelled.", name=exchange.name
                ),
                company=exchange.company_id,
                config=exchange.config_id,
                session=exchange.session_id,
                exchange=exchange,
                return_id=exchange.return_id,
            )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for exchange in records:
            exchange.env["cb.pos.return.audit"]._log_event(
                "exchange_created",
                message=exchange.env._(
                    "Exchange %(name)s created for return %(return_ref)s.",
                    name=exchange.name,
                    return_ref=exchange.return_id.name,
                ),
                company=exchange.company_id,
                config=exchange.config_id,
                session=exchange.session_id,
                exchange=exchange,
                return_id=exchange.return_id,
            )
        return records

    @api.model
    def pos_create_exchange(self, payload, config_id, session_id):
        """POS RPC: create and optionally complete an exchange."""
        if not self.env.user.has_group("cb_pos_return_exchange.group_cb_pos_create_return"):
            raise UserError(self.env._("You are not allowed to create exchanges."))

        config = self.env["pos.config"].browse(config_id).exists()
        session = self.env["pos.session"].browse(session_id).exists()
        if not config or not session:
            raise UserError(self.env._("POS session not found."))
        if session.config_id != config:
            raise UserError(self.env._("POS session does not match the configuration."))

        api = self.env["cb.pos.return.api"]
        disabled = api._require_module_enabled(config)
        if disabled:
            raise UserError(disabled.get("error") or self.env._("Module disabled."))

        return_doc = self.env["cb.pos.return"].browse(payload.get("return_id")).exists()
        replacement = self.env["pos.order"].browse(
            payload.get("replacement_order_id")
        ).exists()
        if not return_doc or not replacement:
            raise UserError(self.env._("Return and replacement order are required."))

        for record, label in (
            (return_doc, self.env._("Return")),
            (replacement, self.env._("POS order")),
        ):
            company_error = api._check_company_record(record, config, label)
            if company_error:
                raise UserError(company_error.get("error"))

        exchange = self.create({
            "return_id": return_doc.id,
            "replacement_order_id": replacement.id,
            "partner_id": return_doc.partner_id.id,
            "company_id": config.company_id.id,
            "currency_id": return_doc.currency_id.id,
            "config_id": config.id,
            "session_id": session.id,
            "cashier_id": self.env.user.id,
            "customer_payment": payload.get("customer_payment", 0.0),
            "voucher_used": bool(payload.get("voucher_used")),
        })

        if payload.get("auto_complete"):
            exchange.action_complete()

        return {
            "id": exchange.id,
            "name": exchange.name,
            "state": exchange.state,
            "difference_amount": exchange.difference_amount,
            "settlement_mode": exchange.settlement_mode,
            "voucher_id": exchange.voucher_id.id if exchange.voucher_id else False,
        }
