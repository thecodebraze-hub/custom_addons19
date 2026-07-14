# -*- coding: utf-8 -*-
"""Customer Display: partner search and selection from the facing screen."""

from odoo import fields, models
from odoo.exceptions import UserError, ValidationError


class PosConfig(models.Model):
    _inherit = "pos.config"

    cb_show_loyalty_points = fields.Boolean(
        string="Show Loyalty Points on Customer Display",
        help="After a customer is selected, show their current loyalty points "
        "on the customer-facing display.",
    )

    def cb_display_search_partners(self, query):
        """Search partners by phone/name for the customer-facing display."""
        self.ensure_one()
        term = (query or "").strip()
        if len(term) < 3:
            return {"success": False, "error": self.env._("Enter at least 3 characters."), "partners": []}

        domain = [
            "|",
            "|",
            ("complete_name", "ilike", term),
            ("phone_mobile_search", "ilike", term),
            ("barcode", "ilike", term),
            ("company_id", "in", [False, self.company_id.id]),
        ]
        partners = self.env["res.partner"].search(domain, limit=20, order="name")
        return {
            "success": True,
            "partners": [
                {
                    "id": partner.id,
                    "name": partner.display_name,
                    "phone": partner.phone or "",
                }
                for partner in partners
            ],
        }

    def cb_display_set_partner(self, partner_id):
        """Push a customer selection from the display to the active POS."""
        self.ensure_one()
        partner = self.env["res.partner"].browse(partner_id).exists()
        if not partner:
            raise UserError(self.env._("Customer not found."))
        if partner.company_id and partner.company_id != self.company_id:
            raise ValidationError(
                self.env._("Customer does not belong to this company.")
            )
        self._notify("CB_DISPLAY_SET_PARTNER", {"partner_id": partner.id})
        return {
            "success": True,
            "partner_id": partner.id,
            "partner_name": partner.display_name,
        }

    def cb_display_clear_partner(self):
        """Ask the active POS to remove the customer from the current order."""
        self.ensure_one()
        self._notify("CB_DISPLAY_SET_PARTNER", {"partner_id": False})
        return {"success": True}

    def cb_display_broadcast_partner(self, partner_id, partner_name):
        """Tell the customer display which customer is set on the POS order."""
        self.ensure_one()
        payload = {
            "partner_id": partner_id or False,
            "partner_name": partner_name or "",
        }
        if partner_id:
            partner = self.env["res.partner"].browse(partner_id).exists()
            loyalty = self._cb_get_loyalty_info(partner) if partner else None
            if loyalty is not None:
                payload["loyalty_points"] = loyalty["points"]
                payload["loyalty_points_label"] = loyalty["label"]
        self._notify("CB_DISPLAY_PARTNER_STATE", payload)
        return True

    def _cb_get_loyalty_info(self, partner):
        """Return the partner's total loyalty points, or ``None`` when the feature
        is off or the loyalty app is not installed.

        We query ``loyalty.card`` directly by ``program_type`` (exactly like Odoo's
        own POS loyalty code) instead of filtering programs by company first, which
        could wrongly exclude the program and yield 0 points.
        """
        self.ensure_one()
        if not self.cb_show_loyalty_points:
            return None
        if "loyalty.card" not in self.env:
            return None

        cards = self.env["loyalty.card"].sudo().search([
            ("partner_id", "=", partner.id),
            ("program_type", "=", "loyalty"),
        ])
        if not cards:
            return {"points": 0.0, "label": self.env._("Points")}

        points = sum(cards.mapped("points"))
        label = cards[:1].program_id.portal_point_name or self.env._("Points")
        return {"points": points, "label": label}
