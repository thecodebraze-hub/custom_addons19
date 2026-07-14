# -*- coding: utf-8 -*-
"""Voucher issuance, redemption, expiry, and cancellation."""

from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class CbPosReturnVoucherLogic(models.Model):
    _inherit = "cb.pos.return.voucher"

    redemption_ids = fields.One2many(
        comodel_name="cb.pos.return.voucher.redemption",
        inverse_name="voucher_id",
        string="Redemptions",
        copy=False,
    )
    audit_ids = fields.One2many(
        comodel_name="cb.pos.return.audit",
        inverse_name="voucher_id",
        string="Audit Trail",
        copy=False,
    )
    credit_note_id = fields.Many2one(
        comodel_name="account.move",
        string="Credit Note",
        related="return_id.account_move_id",
        readonly=True,
    )

    def _get_voucher_config(self):
        self.ensure_one()
        return self.env["cb.pos.return.config"]._get_config(
            company=self.company_id,
            config=self.config_id,
        )

    @api.model
    def _compute_expiry_date(self, settings=None):
        """Compute voucher expiry from configuration."""
        settings = settings or self.env["cb.pos.return.config"]._get_config()
        days = settings.voucher_validity_days if settings else 365
        return fields.Datetime.now() + timedelta(days=days)

    @api.model
    def _issue_from_return(self, return_doc, amount=None):
        """Issue a voucher from a completed or completing return."""
        return_doc.ensure_one()
        amount = amount if amount is not None else return_doc.amount_total
        if float_compare(amount, 0.0, precision_rounding=return_doc.currency_id.rounding) <= 0:
            raise UserError(return_doc.env._("Voucher amount must be positive."))

        settings = return_doc._get_return_config()
        existing = return_doc.voucher_ids.filtered(
            lambda v: v.state in ("draft", "issued", "partial")
        )[:1]
        if existing:
            return existing

        voucher = self.create({
            "return_id": return_doc.id,
            "partner_id": return_doc.partner_id.id,
            "company_id": return_doc.company_id.id,
            "currency_id": return_doc.currency_id.id,
            "config_id": return_doc.config_id.id,
            "session_id": return_doc.session_id.id,
            "amount": amount,
            "state": "issued",
            "issue_date": fields.Datetime.now(),
            "expiry_date": self._compute_expiry_date(settings),
        })
        return_doc.env["cb.pos.return.audit"]._log_event(
            "voucher_issued",
            message=return_doc.env._(
                "Voucher %(voucher)s issued for return %(return_ref)s.",
                voucher=voucher.name,
                return_ref=return_doc.name,
            ),
            amount=amount,
            company=return_doc.company_id,
            config=return_doc.config_id,
            session=return_doc.session_id,
            return_id=return_doc,
            voucher=voucher,
        )
        return voucher

    @api.model
    def _issue_from_exchange(self, exchange, amount):
        """Issue a voucher for a negative exchange difference (store owes customer)."""
        exchange.ensure_one()
        voucher = self.create({
            "exchange_id": exchange.id,
            "return_id": exchange.return_id.id,
            "partner_id": exchange.partner_id.id,
            "company_id": exchange.company_id.id,
            "currency_id": exchange.currency_id.id,
            "config_id": exchange.config_id.id,
            "session_id": exchange.session_id.id,
            "amount": amount,
            "state": "issued",
            "issue_date": fields.Datetime.now(),
            "expiry_date": self._compute_expiry_date(),
        })
        exchange.env["cb.pos.return.audit"]._log_event(
            "voucher_issued",
            message=exchange.env._(
                "Voucher %(voucher)s issued for exchange %(exchange)s.",
                voucher=voucher.name,
                exchange=exchange.name,
            ),
            amount=amount,
            company=exchange.company_id,
            config=exchange.config_id,
            session=exchange.session_id,
            exchange=exchange,
            return_id=exchange.return_id,
            voucher=voucher,
        )
        return voucher

    def _check_redeemable(self):
        self.ensure_one()
        self._expire_if_needed()
        if not self.is_redeemable:
            raise UserError(
                self.env._(
                    "Voucher %(name)s is not redeemable (state: %(state)s).",
                    name=self.name,
                    state=self.state,
                )
            )

    def _apply_redemption_state(self, amount):
        """Update voucher balances and state after a redemption."""
        self.ensure_one()
        rounding = self.currency_id.rounding
        new_redeemed = self.amount_redeemed + amount
        vals = {"amount_redeemed": new_redeemed}
        if float_compare(new_redeemed, self.amount, precision_rounding=rounding) >= 0:
            vals["state"] = "redeemed"
        else:
            vals["state"] = "partial"
        self.write(vals)

    def _redeem(self, amount, pos_order, session=None, issue_remainder=False):
        """
        Redeem voucher value against a POS order.

        Supports partial redemption and optional remainder voucher issuance.
        """
        self.ensure_one()
        if not self.env.user.has_group("cb_pos_return_exchange.group_cb_pos_redeem_voucher"):
            raise AccessError(self.env._("You are not allowed to redeem vouchers."))

        if not pos_order:
            raise ValidationError(self.env._("A POS order is required for redemption."))

        existing = self.env["cb.pos.return.voucher.redemption"].search(
            [
                ("voucher_id", "=", self.id),
                ("pos_order_id", "=", pos_order.id),
            ],
            limit=1,
        )
        if existing:
            raise UserError(
                self.env._(
                    "Voucher %(name)s was already redeemed on this order.",
                    name=self.name,
                )
            )

        settings = self._get_voucher_config()
        rounding = self.currency_id.rounding
        if float_compare(amount, 0.0, precision_rounding=rounding) <= 0:
            raise ValidationError(self.env._("Redemption amount must be positive."))

        self._check_redeemable()

        if (
            float_compare(amount, self.amount_remaining, precision_rounding=rounding) > 0
        ):
            raise UserError(
                self.env._(
                    "Redemption amount %(amount)s exceeds voucher balance %(balance)s.",
                    amount=amount,
                    balance=self.amount_remaining,
                )
            )

        is_partial = float_compare(
            amount, self.amount_remaining, precision_rounding=rounding
        ) < 0
        if is_partial and settings and not settings.allow_partial_voucher_redemption:
            raise UserError(self.env._("Partial voucher redemption is not allowed."))

        remainder_voucher = self.browse()
        if is_partial and issue_remainder and settings and settings.issue_remainder_voucher:
            remaining = self.amount_remaining - amount
            remainder_voucher = self.create({
                "parent_voucher_id": self.id,
                "return_id": self.return_id.id,
                "exchange_id": self.exchange_id.id,
                "partner_id": self.partner_id.id,
                "company_id": self.company_id.id,
                "currency_id": self.currency_id.id,
                "config_id": self.config_id.id,
                "session_id": session.id if session else self.session_id.id,
                "amount": remaining,
                "state": "issued",
                "issue_date": fields.Datetime.now(),
                "expiry_date": self.expiry_date,
            })
            self.write({
                "amount_redeemed": self.amount,
                "state": "redeemed",
            })
            self.env["cb.pos.return.audit"]._log_event(
                "voucher_remainder_created",
                message=self.env._(
                    "Remainder voucher %(voucher)s created with balance %(amount)s.",
                    voucher=remainder_voucher.name,
                    amount=remaining,
                ),
                amount=remaining,
                company=self.company_id,
                config=self.config_id,
                session=session,
                return_id=self.return_id,
                voucher=remainder_voucher,
            )
        else:
            self._apply_redemption_state(amount)

        redemption = self.env["cb.pos.return.voucher.redemption"].create({
            "name": self.env["ir.sequence"].next_by_code("cb.pos.return.voucher.redemption")
            or fields.Datetime.now().strftime("RED/%Y%m%d/%H%M%S"),
            "voucher_id": self.id,
            "pos_order_id": pos_order.id,
            "session_id": session.id if session else False,
            "user_id": self.env.user.id,
            "company_id": self.company_id.id,
            "amount": amount,
            "remainder_voucher_id": remainder_voucher.id,
        })
        self.redemption_order_ids = [(4, pos_order.id)]

        event = "voucher_partial_redeemed" if is_partial else "voucher_redeemed"
        self.env["cb.pos.return.audit"]._log_event(
            event,
            message=self.env._(
                "Redeemed %(amount)s from voucher %(voucher)s on order %(order)s.",
                amount=amount,
                voucher=self.name,
                order=pos_order.display_name,
            ),
            amount=amount,
            company=self.company_id,
            config=self.config_id,
            session=session,
            return_id=self.return_id,
            voucher=self,
            pos_order=pos_order,
        )
        return redemption

    @api.model
    def pos_redeem_voucher(self, barcode, amount, order_id, session_id):
        """POS RPC: redeem a voucher by barcode (delegates to unified API)."""
        session = self.env["pos.session"].browse(session_id).exists()
        if not session:
            raise UserError(self.env._("POS session not found."))
        result = self.env["cb.pos.return.api"].pos_redeem_voucher(
            session.config_id.id,
            session_id,
            barcode,
            amount,
            order_id,
        )
        if not result.get("success"):
            raise UserError(result.get("error") or self.env._("Voucher redemption failed."))
        voucher = result.get("voucher") or {}
        return {
            "voucher_id": voucher.get("id"),
            "voucher_name": voucher.get("name"),
            "amount_redeemed": result.get("redemption", {}).get("amount"),
            "amount_remaining": voucher.get("amount_remaining"),
            "state": voucher.get("state"),
        }

    def action_print_voucher(self):
        """Print voucher thermal receipt and register print event."""
        return self.action_print_voucher_receipt()

    def action_cancel_voucher(self, reason=None):
        """Cancel an issued or partially redeemed voucher (manager only)."""
        if not self.env.user.has_group("cb_pos_return_exchange.group_cb_pos_cancel_voucher"):
            raise AccessError(self.env._("You are not allowed to cancel vouchers."))
        for voucher in self:
            if voucher.state in ("redeemed", "cancelled"):
                raise UserError(
                    voucher.env._(
                        "Voucher %(name)s cannot be cancelled from state %(state)s.",
                        name=voucher.name,
                        state=voucher.state,
                    )
                )
            voucher.write({"state": "cancelled"})
            if reason:
                voucher.message_post(body=reason)
            voucher.env["cb.pos.return.audit"]._log_event(
                "voucher_cancelled",
                message=voucher.env._(
                    "Voucher %(name)s cancelled.%(reason)s",
                    name=voucher.name,
                    reason=f" {reason}" if reason else "",
                ),
                success=True,
                company=voucher.company_id,
                config=voucher.config_id,
                return_id=voucher.return_id,
                voucher=voucher,
            )
        return True

    def _expire_if_needed(self):
        """Mark voucher expired when past expiry date."""
        for voucher in self:
            if (
                voucher.expiry_date
                and voucher.expiry_date < fields.Datetime.now()
                and voucher.state in ("issued", "partial")
            ):
                voucher._set_expired()

    def _set_expired(self):
        self.ensure_one()
        self.write({"state": "expired"})
        self.env["cb.pos.return.audit"]._log_event(
            "voucher_expired",
            message=self.env._("Voucher %(name)s expired.", name=self.name),
            company=self.company_id,
            config=self.config_id,
            return_id=self.return_id,
            voucher=self,
        )

    @api.model
    def _cron_expire_vouchers(self):
        """Scheduled job: expire all vouchers past their expiry date."""
        now = fields.Datetime.now()
        vouchers = self.search([
            ("state", "in", ("issued", "partial")),
            ("expiry_date", "!=", False),
            ("expiry_date", "<", now),
        ])
        for voucher in vouchers:
            voucher._set_expired()
        return True

    @api.model
    def pos_lookup_voucher(self, barcode, config_id):
        """POS RPC: fetch voucher details by barcode (delegates to unified API)."""
        result = self.env["cb.pos.return.api"].pos_validate_voucher(
            config_id, False, barcode
        )
        if not result.get("success"):
            raise UserError(result.get("error") or self.env._("Voucher not found."))
        voucher = result.get("voucher") or {}
        return voucher
