from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class LiquorOpenBottle(models.Model):
    _name = "liquor.open.bottle"
    _description = "Opened Liquor Bottle"
    _order = "opened_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        domain="[('is_storable', '=', True)]",
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    bottle_size_ml = fields.Float(string="Bottle Size (ml)", required=True, default=750.0)
    remaining_ml = fields.Float(string="Remaining ML", required=True)
    opened_date = fields.Datetime(string="Opened Date", default=fields.Datetime.now, required=True)
    last_updated = fields.Datetime(string="Last Updated", compute="_compute_last_updated")
    state = fields.Selection(
        [("open", "Open"), ("closed", "Closed")],
        default="open",
        required=True,
        index=True,
    )
    opening_picking_id = fields.Many2one("stock.picking", string="Opening Transfer", readonly=True)
    pos_order_id = fields.Many2one("pos.order", string="Opened From POS Order", readonly=True)

    @api.depends("product_id", "remaining_ml", "state")
    def _compute_name(self):
        for bottle in self:
            product_name = bottle.product_id.display_name or _("Bottle")
            bottle.name = _(
                "%(product)s - %(remaining)sml (%(state)s)",
                product=product_name,
                remaining=bottle._format_qty(bottle.remaining_ml),
                state=dict(bottle._fields["state"].selection).get(bottle.state),
            )

    def _compute_last_updated(self):
        for bottle in self:
            bottle.last_updated = bottle.write_date or bottle.create_date or fields.Datetime.now()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("product_id") and not vals.get("bottle_size_ml"):
                product = self.env["product.product"].browse(vals["product_id"])
                vals["bottle_size_ml"] = product.liquor_bottle_size_ml or 750.0
            if vals.get("remaining_ml") is None:
                vals["remaining_ml"] = vals.get("bottle_size_ml") or 750.0
        records = super().create(vals_list)
        records._check_single_open_bottle()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {"product_id", "company_id", "state"} & set(vals):
            self._check_single_open_bottle()
        return result

    @api.constrains("remaining_ml", "bottle_size_ml")
    def _check_remaining_ml(self):
        for bottle in self:
            if bottle.bottle_size_ml <= 0:
                raise ValidationError(_("Bottle size must be positive."))
            if float_compare(bottle.remaining_ml, 0.0, precision_digits=2) < 0:
                raise ValidationError(_("Remaining ML cannot be negative."))
            if float_compare(bottle.remaining_ml, bottle.bottle_size_ml, precision_digits=2) > 0:
                raise ValidationError(_("Remaining ML cannot exceed bottle size."))

    @api.constrains("product_id", "company_id", "state")
    def _check_single_open_bottle(self):
        for bottle in self.filtered(lambda record: record.state == "open"):
            domain = [
                ("id", "!=", bottle.id),
                ("product_id", "=", bottle.product_id.id),
                ("company_id", "=", bottle.company_id.id),
                ("state", "=", "open"),
            ]
            if self.search_count(domain):
                raise ValidationError(_("Only one opened bottle can be active per product."))

    @api.model
    def consume_from_pos_order(self, product, consumption_ml, order):
        if float_compare(consumption_ml, 0.0, precision_digits=2) <= 0:
            return

        product = product.with_company(order.company_id)
        bottle_size = product.liquor_bottle_size_ml or 750.0
        source_location = order._liquor_get_source_location()
        open_bottle = self._get_open_bottle(product, order.company_id, for_update=True)
        available_ml = (open_bottle.remaining_ml if open_bottle else 0.0) + (
            product.with_context(location=source_location.id).qty_available * bottle_size
        )
        if float_compare(available_ml, consumption_ml, precision_digits=2) < 0:
            raise UserError(_(
                "Not enough full bottle stock for %(product)s shots. Required: %(required)sml, Available: %(available)sml.",
                product=product.display_name,
                required=self._format_qty(consumption_ml),
                available=self._format_qty(available_ml),
            ))

        remaining_to_consume = consumption_ml
        while float_compare(remaining_to_consume, 0.0, precision_digits=2) > 0:
            open_bottle = self._get_open_bottle(product, order.company_id, for_update=True)
            if not open_bottle or float_is_zero(open_bottle.remaining_ml, precision_digits=2):
                open_bottle = self._open_new_bottle(product, order)

            consumed_ml = min(open_bottle.remaining_ml, remaining_to_consume)
            new_remaining = open_bottle.remaining_ml - consumed_ml
            vals = {"remaining_ml": new_remaining}
            if float_is_zero(new_remaining, precision_digits=2):
                vals.update({"remaining_ml": 0.0, "state": "closed"})
            open_bottle.write(vals)
            remaining_to_consume -= consumed_ml

    def _get_open_bottle(self, product, company, for_update=False):
        bottle = self.search([
            ("product_id", "=", product.id),
            ("company_id", "=", company.id),
            ("state", "=", "open"),
        ], limit=1)
        if bottle and for_update:
            self.env.cr.execute(
                "SELECT id FROM liquor_open_bottle WHERE id = %s FOR UPDATE",
                [bottle.id],
            )
        return bottle

    def _open_new_bottle(self, product, order):
        source_location = order._liquor_get_source_location()
        if float_compare(product.with_context(location=source_location.id).qty_available, 1.0, precision_digits=2) < 0:
            raise UserError(_("No sealed full bottle is available for %s.", product.display_name))

        picking = self._create_opening_stock_move(product, order)
        return self.create({
            "product_id": product.id,
            "company_id": order.company_id.id,
            "bottle_size_ml": product.liquor_bottle_size_ml or 750.0,
            "remaining_ml": product.liquor_bottle_size_ml or 750.0,
            "opening_picking_id": picking.id,
            "pos_order_id": order.id,
        })

    def _create_opening_stock_move(self, product, order):
        picking_type = order.config_id.picking_type_id
        source_location = order._liquor_get_source_location()
        destination_location = order._liquor_get_destination_location()
        picking = self.env["stock.picking"].sudo().create({
            "partner_id": order.partner_id.id,
            "user_id": False,
            "picking_type_id": picking_type.id,
            "move_type": "direct",
            "location_id": source_location.id,
            "location_dest_id": destination_location.id,
            "state": "draft",
            "pos_session_id": order.session_id.id,
            "pos_order_id": order.id,
            "origin": order.name,
        })
        move = self.env["stock.move"].sudo().create({
            "product_id": product.id,
            "product_uom": product.uom_id.id,
            "product_uom_qty": 1.0,
            "picking_id": picking.id,
            "picking_type_id": picking_type.id,
            "location_id": source_location.id,
            "location_dest_id": destination_location.id,
            "company_id": order.company_id.id,
            "origin": order.name,
        })
        move._action_confirm()
        move._set_quantity_done(1.0)
        move.picked = True
        picking._action_done()
        return picking

    @api.model
    def _format_qty(self, value):
        value = value or 0.0
        if float(value).is_integer():
            return str(int(value))
        return f"{value:g}"
