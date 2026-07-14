# -*- coding: utf-8 -*-

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    cb_require_cancel_approval = fields.Boolean(
        string="Manager Approval to Cancel Order",
        help="Require a POS manager PIN before an order that has items can be "
        "cancelled from the Point of Sale.",
    )

    def cb_verify_cancel_manager_pin(self, pin):
        """Validate an approver PIN for approving an order cancellation.

        Returns a dict with ``success`` and, on success, the approving
        user's id and name. Only users in the "POS Cancel Approver" group with a
        matching approval PIN are accepted.
        """
        self.ensure_one()
        pin = (pin or "").strip()
        if not pin:
            return {"success": False, "error": self.env._("Enter the approver PIN.")}

        candidates = self.env["res.users"].sudo().search([
            ("cb_pos_manager_pin", "!=", False),
        ])
        manager = candidates.filtered(
            lambda user: (user.cb_pos_manager_pin or "").strip() == pin
            and user.has_group(
                "cb_pos_cancel_approval.group_cb_pos_cancel_approver"
            )
        )[:1]

        if not manager:
            return {"success": False, "error": self.env._("Invalid approver PIN.")}

        return {
            "success": True,
            "manager_id": manager.id,
            "manager_name": manager.name,
        }

    def cb_log_cancel_approval(self, vals):
        """Persist an approval audit entry for a cancelled order or removed line."""
        self.ensure_one()
        reason = (vals.get("reason") or "").strip()
        if not reason:
            return {"success": False, "error": self.env._("Enter a reason.")}

        session_id = vals.get("session_id")
        session = self.env["pos.session"].browse(session_id).exists() if session_id else False

        self.env["cb.pos.cancel.approval.log"].sudo().create({
            "action_type": vals.get("action_type") or "cancel_order",
            "config_id": self.id,
            "session_id": session.id if session else False,
            "cashier_id": self.env.user.id,
            "manager_id": vals.get("manager_id"),
            "order_reference": vals.get("order_reference") or "",
            "product_name": vals.get("product_name") or "",
            "amount": float(vals.get("amount") or 0.0),
            "currency_id": self.currency_id.id,
            "reason": reason,
        })
        return {"success": True}
