# -*- coding: utf-8 -*-
"""Inventory integration for POS returns."""

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CbPosReturnStock(models.Model):
    _inherit = "cb.pos.return"

    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        compute="_compute_warehouse_id",
        store=True,
        check_company=True,
    )
    picking_ids = fields.One2many(
        comodel_name="stock.picking",
        inverse_name="cb_pos_return_id",
        string="Stock Pickings",
        copy=False,
    )
    picking_count = fields.Integer(compute="_compute_picking_count")
    stock_move_ids = fields.Many2many(
        comodel_name="stock.move",
        compute="_compute_stock_move_ids",
        string="Stock Moves",
    )

    @api.depends("config_id", "config_id.picking_type_id", "config_id.warehouse_id")
    def _compute_warehouse_id(self):
        for record in self:
            warehouse = False
            if record.config_id:
                if record.config_id.warehouse_id:
                    warehouse = record.config_id.warehouse_id
                elif record.config_id.picking_type_id:
                    warehouse = record.config_id.picking_type_id.warehouse_id
            record.warehouse_id = warehouse

    @api.depends("picking_ids")
    def _compute_picking_count(self):
        for record in self:
            record.picking_count = len(record.picking_ids)

    @api.depends("picking_ids.move_ids")
    def _compute_stock_move_ids(self):
        for record in self:
            record.stock_move_ids = record.picking_ids.move_ids

    def _get_stockable_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: line.product_id.is_storable
            and not line.product_id.uom_id.is_zero(line.qty)
        )

    def _get_customer_location(self):
        """Customer location used as the source for return pickings."""
        self.ensure_one()
        picking_type = self.config_id.picking_type_id
        partner = self.partner_id or self.original_order_id.partner_id
        if partner and partner.property_stock_customer:
            return partner.property_stock_customer
        if picking_type and picking_type.default_location_dest_id:
            return picking_type.default_location_dest_id
        return self.env["stock.warehouse"]._get_partner_locations()[0]

    def _get_return_picking_type(self):
        self.ensure_one()
        picking_type = self.config_id.picking_type_id
        if not picking_type:
            raise UserError(
                self.env._(
                    "POS configuration %(config)s has no operation type configured.",
                    config=self.config_id.display_name,
                )
            )
        return picking_type.return_picking_type_id or picking_type

    def _get_disposition_location(self, disposition):
        """Resolve destination location based on return line disposition."""
        self.ensure_one()
        picking_type = self.config_id.picking_type_id
        warehouse = self.warehouse_id
        settings = self._get_return_config()

        if disposition == "scrap":
            scrap_location = self.company_id.scrap_location_id
            if not scrap_location:
                raise UserError(
                    self.env._(
                        "No scrap location is configured for company %(company)s.",
                        company=self.company_id.display_name,
                    )
                )
            return scrap_location

        if disposition == "quarantine":
            if settings and settings.quarantine_location_id:
                return settings.quarantine_location_id
            raise UserError(
                self.env._(
                    "Configure a quarantine location in Return & Exchange settings "
                    "before processing quarantine returns."
                )
            )

        # Restock: goods must return to an internal stock location. Only trust
        # a genuinely-configured return/incoming picking type's destination.
        # Otherwise the return type falls back to the outgoing POS type whose
        # destination is the customer location — which would (incorrectly) send
        # the returned goods straight back to Customers.
        configured_return_type = picking_type.return_picking_type_id
        if (
            configured_return_type
            and configured_return_type.default_location_dest_id
            and configured_return_type.default_location_dest_id.usage == "internal"
        ):
            return configured_return_type.default_location_dest_id
        if picking_type and picking_type.default_location_src_id:
            return picking_type.default_location_src_id
        if warehouse:
            return warehouse.lot_stock_id
        raise UserError(self.env._("No stock location found for return restocking."))

    def _validate_stock(self):
        """Validate inventory rules before confirming the return."""
        self.ensure_one()
        errors = []
        settings = self._get_return_config()
        precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")

        if not self.config_id.picking_type_id:
            errors.append(
                self.env._(
                    "POS configuration %(config)s must have an operation type to process stock returns.",
                    config=self.config_id.display_name,
                )
            )

        for line in self.line_ids:
            errors.extend(line._get_stock_validation_errors(settings, precision))

        if errors:
            message = "\n".join(errors)
            self.env["cb.pos.return.audit"]._log_event(
                "stock_validation_failure",
                message=message,
                success=False,
                company=self.company_id,
                config=self.config_id,
                session=self.session_id,
                return_id=self,
                pos_order=self.original_order_id,
                payload={"errors": errors},
            )
            raise ValidationError(message)
        return True

    def _find_original_delivery_move(self, line):
        """Find the outbound stock move from the original POS sale."""
        order = line.return_id.original_order_id
        moves = order.picking_ids.move_ids.filtered(
            lambda move: move.state == "done"
            and move.product_id == line.product_id
            and move.location_dest_usage == "customer"
        )
        if line.lot_id:
            moves = moves.filtered(
                lambda move: line.lot_id in move.move_line_ids.lot_id
            )
        if not moves and line.original_line_id.attribute_value_ids:
            moves = order.picking_ids.move_ids.filtered(
                lambda move: move.state == "done"
                and move.product_id == line.product_id
            )
        return moves[:1]

    def _prepare_return_move_vals(self, line, picking, location_src, location_dest):
        self.ensure_one()
        original_move = self._find_original_delivery_move(line)
        vals = {
            "product_id": line.product_id.id,
            "product_uom_qty": line.qty,
            "product_uom": line.uom_id.id,
            "picking_id": picking.id,
            "picking_type_id": picking.picking_type_id.id,
            "location_id": location_src.id,
            "location_dest_id": location_dest.id,
            "company_id": self.company_id.id,
            "warehouse_id": picking.picking_type_id.warehouse_id.id,
            "partner_id": self.partner_id.id or False,
            "cb_pos_return_line_id": line.id,
            "description_picking": line.product_id.display_name,
        }
        if original_move:
            vals["origin_returned_move_id"] = original_move.id
            vals["move_orig_ids"] = [Command.link(original_move.id)]
        if line.original_line_id.attribute_value_ids:
            vals["never_product_template_attribute_value_ids"] = [
                Command.set(
                    line.original_line_id.attribute_value_ids.filtered(
                        lambda av: av.attribute_id.create_variant == "no_variant"
                    ).ids
                )
            ]
        return vals

    def _create_return_move_lines(self, move, line):
        """Create done move lines including lot/serial traceability."""
        line.ensure_one()
        move.ensure_one()
        ml_vals = {
            "move_id": move.id,
            "product_id": line.product_id.id,
            "product_uom_id": line.uom_id.id,
            "quantity": line.qty,
            "location_id": move.location_id.id,
            "location_dest_id": move.location_dest_id.id,
        }
        if line.lot_id:
            ml_vals["lot_id"] = line.lot_id.id
        self.env["stock.move.line"].create(ml_vals)

    def _create_return_picking_for_disposition(self, lines, disposition):
        """Create and validate one return picking for a disposition group."""
        self.ensure_one()
        if not lines:
            return self.env["stock.picking"]

        location_src = self._get_customer_location()
        location_dest = self._get_disposition_location(disposition)
        return_picking_type = self._get_return_picking_type()

        picking = self.env["stock.picking"].create({
            "partner_id": self.partner_id.id or False,
            "picking_type_id": return_picking_type.id,
            "location_id": location_src.id,
            "location_dest_id": location_dest.id,
            "origin": self.env._("Return %(name)s", name=self.name),
            "company_id": self.company_id.id,
            "cb_pos_return_id": self.id,
            "pos_session_id": self.session_id.id if self.session_id else False,
            "pos_order_id": self.original_order_id.id,
        })

        for line in lines:
            move = self.env["stock.move"].create(
                self._prepare_return_move_vals(line, picking, location_src, location_dest)
            )
            line.move_id = move.id

        picking.action_confirm()

        for move in picking.move_ids:
            line = move.cb_pos_return_line_id
            if line:
                self._create_return_move_lines(move, line)

        settings = self._get_return_config()
        if not settings or settings.auto_validate_return_picking:
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.button_validate()

        self.env["cb.pos.return.audit"]._log_event(
            "stock_picking_created",
            message=self.env._(
                "Stock picking %(picking)s created for return %(return_ref)s (%(disposition)s).",
                picking=picking.name,
                return_ref=self.name,
                disposition=disposition,
            ),
            company=self.company_id,
            config=self.config_id,
            session=self.session_id,
            return_id=self,
            pos_order=self.original_order_id,
            payload={
                "picking_id": picking.id,
                "disposition": disposition,
                "line_ids": lines.ids,
            },
        )

        if picking.state == "done":
            self.env["cb.pos.return.audit"]._log_event(
                "stock_picking_validated",
                message=self.env._(
                    "Stock picking %(picking)s validated for return %(return_ref)s.",
                    picking=picking.name,
                    return_ref=self.name,
                ),
                company=self.company_id,
                config=self.config_id,
                session=self.session_id,
                return_id=self,
                pos_order=self.original_order_id,
                payload={"picking_id": picking.id},
            )

        if not self.picking_id:
            self.picking_id = picking.id
        return picking

    def _create_return_stock_pickings(self):
        """Create stock pickings and moves for all storable return lines."""
        self.ensure_one()
        if self.picking_ids:
            return self.picking_ids

        stockable_lines = self._get_stockable_lines()
        if not stockable_lines:
            return self.env["stock.picking"]

        pickings = self.env["stock.picking"]
        for disposition, grouped_lines in stockable_lines.grouped("disposition").items():
            pickings |= self._create_return_picking_for_disposition(
                grouped_lines, disposition
            )
        return pickings

    def _cancel_return_stock_pickings(self):
        """Cancel open stock pickings linked to the return."""
        for record in self:
            open_pickings = record.picking_ids.filtered(
                lambda picking: picking.state not in ("done", "cancel")
            )
            done_pickings = record.picking_ids.filtered(
                lambda picking: picking.state == "done"
            )
            if done_pickings and record.state != "done":
                raise UserError(
                    record.env._(
                        "Cannot cancel return %(name)s because stock pickings are already done.",
                        name=record.name,
                    )
                )
            open_pickings.action_cancel()

    def action_view_pickings(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock.action_picking_tree_all"
        )
        action["domain"] = [("id", "in", self.picking_ids.ids)]
        if len(self.picking_ids) == 1:
            action["views"] = [(False, "form")]
            action["res_id"] = self.picking_ids.id
        return action
