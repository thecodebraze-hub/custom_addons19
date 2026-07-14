# -*- coding: utf-8 -*-
"""Stock validation helpers for return lines."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class CbPosReturnLineStock(models.Model):
    _inherit = "cb.pos.return.line"

    attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        related="original_line_id.attribute_value_ids",
        string="Product Variants",
        readonly=True,
    )
    product_tracking = fields.Selection(
        related="product_id.tracking",
        string="Tracking",
        readonly=True,
    )
    move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        compute="_compute_move_line_ids",
        string="Stock Move Lines",
    )

    @api.depends("move_id.move_line_ids")
    def _compute_move_line_ids(self):
        for line in self:
            line.move_line_ids = line.move_id.move_line_ids

    def _get_sold_lot_names(self):
        """Lot/serial names delivered on the original POS order line."""
        self.ensure_one()
        lot_names = set(self.original_line_id.pack_lot_ids.mapped("lot_name"))
        order = self.return_id.original_order_id
        for move in order.picking_ids.move_ids.filtered(
            lambda m: m.state == "done" and m.product_id == self.product_id
        ):
            for move_line in move.move_line_ids.filtered(
                lambda ml: ml.lot_id and ml.product_id == self.product_id
            ):
                lot_names.add(move_line.lot_id.name)
        return lot_names

    def _get_stock_validation_errors(self, settings, precision):
        self.ensure_one()
        errors = []
        product = self.product_id

        if not product.is_storable:
            return errors

        if product.tracking != "none":
            if not self.lot_id:
                errors.append(
                    self.env._(
                        "Lot/serial number is required for tracked product %(product)s.",
                        product=product.display_name,
                    )
                )
            elif self.lot_id.product_id != product:
                errors.append(
                    self.env._(
                        "Lot/serial %(lot)s does not belong to product %(product)s.",
                        lot=self.lot_id.name,
                        product=product.display_name,
                    )
                )
            elif settings and settings.validate_lot_from_sale:
                sold_lots = self._get_sold_lot_names()
                if sold_lots and self.lot_id.name not in sold_lots:
                    errors.append(
                        self.env._(
                            "Lot/serial %(lot)s was not sold on the original order for %(product)s.",
                            lot=self.lot_id.name,
                            product=product.display_name,
                        )
                    )

            if product.tracking == "serial":
                if float_compare(self.qty, 1.0, precision_digits=precision) != 0:
                    errors.append(
                        self.env._(
                            "Serial tracked product %(product)s must be returned one unit per line.",
                            product=product.display_name,
                        )
                    )

        if self.uom_id != product.uom_id:
            try:
                product.uom_id._compute_quantity(1.0, self.uom_id, round=False)
            except Exception:
                errors.append(
                    self.env._(
                        "Unit of measure %(uom)s is not compatible with %(product)s.",
                        uom=self.uom_id.display_name,
                        product=product.display_name,
                    )
                )

        return errors

    @api.onchange("product_id")
    def _onchange_product_id_stock(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id

    @api.constrains("lot_id", "product_id", "qty")
    def _check_lot_serial_constraints(self):
        precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        for line in self:
            if line.product_id.tracking == "serial" and line.lot_id:
                if float_compare(line.qty, 1.0, precision_digits=precision) != 0:
                    raise ValidationError(
                        line.env._(
                            "Quantity must be 1 for serial number %(lot)s.",
                            lot=line.lot_id.name,
                        )
                    )
