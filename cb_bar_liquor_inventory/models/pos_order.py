from collections import defaultdict

from odoo import fields, models, _
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    liquor_shot_consumed = fields.Boolean(
        string="Liquor Shot Stock Consumed",
        copy=False,
        readonly=True,
    )

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        for order in self:
            order._liquor_consume_shot_lines()
        return result

    def _liquor_consume_shot_lines(self):
        self.ensure_one()
        if self.liquor_shot_consumed:
            return

        consumption_by_parent = defaultdict(float)
        for line in self.lines.filtered(lambda order_line: order_line.qty > 0):
            product = line.product_id
            if not product.liquor_is_liquor or not product.liquor_is_shot_product:
                continue
            parent = product.liquor_parent_bottle_product_id
            if not parent:
                raise UserError(_("Shot product %s has no parent bottle product.", product.display_name))
            if product.liquor_consumption_ml <= 0:
                raise UserError(_("Shot product %s must have a positive consumption ML.", product.display_name))
            consumption_by_parent[parent.id] += product.liquor_consumption_ml * line.qty

        if not consumption_by_parent:
            return

        open_bottle_model = self.env["liquor.open.bottle"]
        for parent_id, total_ml in consumption_by_parent.items():
            parent = self.env["product.product"].browse(parent_id)
            open_bottle_model.consume_from_pos_order(parent, total_ml, self)

        self.liquor_shot_consumed = True

    def _liquor_get_source_location(self):
        self.ensure_one()
        picking_type = self.config_id.picking_type_id
        if not picking_type or not picking_type.default_location_src_id:
            raise UserError(_("Please configure a source stock location on the POS operation type."))
        return picking_type.default_location_src_id

    def _liquor_get_destination_location(self):
        self.ensure_one()
        picking_type = self.config_id.picking_type_id
        if self.partner_id.property_stock_customer:
            return self.partner_id.property_stock_customer
        if picking_type and picking_type.default_location_dest_id:
            return picking_type.default_location_dest_id
        return self.env["stock.warehouse"]._get_partner_locations()[0]
