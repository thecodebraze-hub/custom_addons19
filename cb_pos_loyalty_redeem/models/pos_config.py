# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    cb_loyalty_redeem_enabled = fields.Boolean(
        string="Custom Loyalty Redemption",
        help="Allow cashiers to redeem a custom amount of the customer's loyalty "
        "points as a discount on the order.",
    )
    cb_loyalty_program_id = fields.Many2one(
        comodel_name="loyalty.program",
        string="Loyalty Program",
        domain="[('program_type', '=', 'loyalty')]",
        help="The loyalty program whose points can be redeemed at this POS.",
    )
    cb_loyalty_redeem_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Redemption Product",
        default=lambda self: self.env.ref(
            "cb_pos_loyalty_redeem.product_product_loyalty_redeem",
            raise_if_not_found=False,
        ),
        help="Product used for the negative discount line added when points are "
        "redeemed.",
    )
    cb_loyalty_point_rate = fields.Float(
        string="Point Value",
        default=1.0,
        digits=(16, 4),
        help="Currency value of a single point. Example: 1 means 1 point = 1.00, "
        "0.1 means 10 points = 1.00.",
    )
    cb_loyalty_min_points = fields.Float(
        string="Minimum Points",
        default=0.0,
        help="Minimum number of points required before a redemption is allowed. "
        "0 means no minimum.",
    )

    @api.model
    def _cb_default_loyalty_redeem_product(self):
        return self.env.ref(
            "cb_pos_loyalty_redeem.product_product_loyalty_redeem",
            raise_if_not_found=False,
        )

    @api.onchange("cb_loyalty_redeem_enabled")
    def _onchange_cb_loyalty_redeem_enabled(self):
        if self.cb_loyalty_redeem_enabled and not self.cb_loyalty_redeem_product_id:
            self.cb_loyalty_redeem_product_id = self._cb_default_loyalty_redeem_product()

    def write(self, vals):
        res = super().write(vals)
        if vals.get("cb_loyalty_redeem_enabled"):
            default_product = self._cb_default_loyalty_redeem_product()
            for config in self:
                if config.cb_loyalty_redeem_enabled and not config.cb_loyalty_redeem_product_id and default_product:
                    super(PosConfig, config).write(
                        {"cb_loyalty_redeem_product_id": default_product.id}
                    )
        return res

    def _get_special_products(self):
        products = super()._get_special_products()
        default_product = self._cb_default_loyalty_redeem_product() or self.env["product.product"]
        configured = self.env["pos.config"].search([]).mapped("cb_loyalty_redeem_product_id")
        return products | configured | default_product

    def cb_get_partner_loyalty_balance(self, partner_id):
        """Return the partner's redeemable balance + card for this POS.

        Reads the loyalty card directly from the database (not the POS cache),
        so it always reflects the real balance even if the card was not loaded
        into the POS session yet.

        If a specific program is set on the config, only that program's cards
        are used. Otherwise all active Loyalty Cards programs are summed.
        """
        self.ensure_one()
        if not partner_id:
            return {
                "points": 0.0,
                "card_id": False,
                "label": self.env._("Points"),
                "error": self.env._("No customer selected."),
            }

        domain = [
            ("partner_id", "=", partner_id),
            ("program_type", "=", "loyalty"),
            ("program_id.active", "=", True),
        ]
        program = self.cb_loyalty_program_id
        if program:
            domain.append(("program_id", "=", program.id))

        cards = self.env["loyalty.card"].sudo().search(domain, order="points desc")
        if not cards:
            # Helpful diagnostics for the cashier.
            if program:
                error = self.env._(
                    "No loyalty card found for this customer in program "
                    "\"%(program)s\". Points earned on a different program "
                    "cannot be redeemed here. Finish a paid sale first, or "
                    "check the Loyalty Program setting.",
                    program=program.name,
                )
            else:
                error = self.env._(
                    "This customer has no loyalty card yet. Points shown on "
                    "the order are earned only after payment — they are not "
                    "available to redeem on this same unpaid order.",
                )
            return {
                "points": 0.0,
                "card_id": False,
                "label": (program.portal_point_name if program else None)
                or self.env._("Points"),
                "error": error,
            }

        points = sum(cards.mapped("points"))
        label = (
            cards[:1].program_id.portal_point_name
            or (program.portal_point_name if program else None)
            or self.env._("Points")
        )
        return {
            "points": points,
            "card_id": cards[:1].id,
            "label": label,
            "error": False if points > 0 else self.env._(
                "This customer has a loyalty card, but the balance is 0. "
                "Points earned on the current order are added only after payment."
            ),
        }
