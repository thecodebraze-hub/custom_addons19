# -*- coding: utf-8 -*-

from odoo import _, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    cb_loyalty_redeem_points = fields.Float(
        string="Redeemed Loyalty Points",
        readonly=True,
        copy=False,
        help="Loyalty points redeemed on this order via custom redemption.",
    )
    cb_loyalty_redeem_amount = fields.Monetary(
        string="Redeemed Amount",
        currency_field="currency_id",
        readonly=True,
        copy=False,
    )
    cb_loyalty_redeem_card_id = fields.Many2one(
        comodel_name="loyalty.card",
        string="Redeemed Loyalty Card",
        readonly=True,
        copy=False,
    )
    cb_loyalty_redeem_applied = fields.Boolean(
        string="Loyalty Redemption Applied",
        readonly=True,
        copy=False,
    )

    def _process_saved_order(self, draft):
        res = super()._process_saved_order(draft)
        if not draft and self.state != "cancel":
            self._cb_apply_loyalty_redemption()
        return res

    def _cb_apply_loyalty_redemption(self):
        """Deduct redeemed points from the customer's loyalty card once paid."""
        self.ensure_one()
        if (
            self.cb_loyalty_redeem_applied
            or not self.cb_loyalty_redeem_points
            or not self.cb_loyalty_redeem_card_id
        ):
            return

        card = self.cb_loyalty_redeem_card_id.sudo()
        if not card.exists():
            return

        points = self.cb_loyalty_redeem_points
        card.points = max(0.0, card.points - points)
        self.env["loyalty.history"].sudo().create({
            "card_id": card.id,
            "order_model": self._name,
            "order_id": self.id,
            "description": _("POS custom loyalty redemption: %s", self.display_name),
            "used": points,
            "issued": 0,
        })
        self.cb_loyalty_redeem_applied = True

    def action_pos_order_cancel(self):
        res = super().action_pos_order_cancel()
        for order in self:
            order._cb_restore_loyalty_redemption()
        return res

    def _cb_restore_loyalty_redemption(self):
        """Restore points when a paid order with custom redemption is cancelled."""
        self.ensure_one()
        if (
            not self.cb_loyalty_redeem_applied
            or not self.cb_loyalty_redeem_points
            or not self.cb_loyalty_redeem_card_id
        ):
            return

        card = self.cb_loyalty_redeem_card_id.sudo()
        if not card.exists():
            return

        points = self.cb_loyalty_redeem_points
        card.points += points
        self.env["loyalty.history"].sudo().create({
            "card_id": card.id,
            "order_model": self._name,
            "order_id": self.id,
            "description": _("POS loyalty redemption restored: %s", self.display_name),
            "used": 0,
            "issued": points,
        })
        self.cb_loyalty_redeem_applied = False
