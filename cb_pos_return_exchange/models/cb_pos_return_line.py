# -*- coding: utf-8 -*-
"""POS return transaction lines."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class CbPosReturnLine(models.Model):
  """
  POS return line.

  Technical name: cb.pos.return.line

  Represents a single product line being returned, including quantity,
  pricing, taxes, stock disposition, and linkage to the original sale line.
  """

  _name = "cb.pos.return.line"
  _description = "POS Return Line"
  _order = "return_id, sequence, id"
  _check_company_auto = True

  return_id = fields.Many2one(
      comodel_name="cb.pos.return",
      string="Return",
      required=True,
      ondelete="cascade",
      index=True,
  )
  sequence = fields.Integer(default=10)
  active = fields.Boolean(related="return_id.active", store=True)
  state = fields.Selection(related="return_id.state", store=True, index=True)
  company_id = fields.Many2one(
      comodel_name="res.company",
      related="return_id.company_id",
      store=True,
      index=True,
      readonly=True,
  )
  currency_id = fields.Many2one(
      comodel_name="res.currency",
      related="return_id.currency_id",
      store=True,
      readonly=True,
  )

  original_line_id = fields.Many2one(
      comodel_name="pos.order.line",
      string="Original Order Line",
      required=True,
      index=True,
      ondelete="restrict",
  )
  product_id = fields.Many2one(
      comodel_name="product.product",
      string="Product",
      required=True,
      index=True,
  )
  uom_id = fields.Many2one(
      comodel_name="uom.uom",
      string="Unit of Measure",
      required=True,
  )
  qty_sold = fields.Float(
      string="Qty Sold",
      digits="Product Unit of Measure",
      help="Quantity sold on the original order line.",
  )
  qty_returned_prev = fields.Float(
      string="Qty Already Returned",
      digits="Product Unit of Measure",
      default=0.0,
      help="Quantity previously returned against the original line.",
  )
  qty = fields.Float(
      string="Qty To Return",
      digits="Product Unit of Measure",
      required=True,
      default=1.0,
  )
  qty_remaining = fields.Float(
      string="Qty Remaining After Return",
      digits="Product Unit of Measure",
      compute="_compute_qty_remaining",
      store=True,
  )
  price_unit = fields.Float(
      string="Unit Price",
      digits="Product Price",
      required=True,
  )
  discount = fields.Float(string="Discount (%)", default=0.0)
  tax_ids = fields.Many2many(
      comodel_name="account.tax",
      relation="cb_pos_return_line_tax_rel",
      column1="line_id",
      column2="tax_id",
      string="Taxes",
  )
  price_subtotal = fields.Monetary(
      string="Subtotal",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
  )
  price_tax = fields.Monetary(
      string="Tax Amount",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
  )
  price_total = fields.Monetary(
      string="Total",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
  )
  reason = fields.Char(string="Line Reason")
  disposition = fields.Selection(
      selection=[
          ("restock", "Restock"),
          ("scrap", "Scrap"),
          ("quarantine", "Quarantine"),
      ],
      string="Disposition",
      default="restock",
      required=True,
      index=True,
  )
  lot_id = fields.Many2one(
      comodel_name="stock.lot",
      string="Lot/Serial",
      check_company=True,
      index=True,
  )
  move_id = fields.Many2one(
      comodel_name="stock.move",
      string="Stock Move",
      copy=False,
      index=True,
      check_company=True,
  )

  _qty_positive = models.Constraint(
      "CHECK(qty > 0)",
      "Return quantity must be greater than zero.",
  )
  _price_unit_positive = models.Constraint(
      "CHECK(price_unit >= 0)",
      "Unit price cannot be negative.",
  )
  _return_product_idx = models.Index("(return_id, product_id)")

  @api.depends("qty_sold", "qty_returned_prev", "qty")
  def _compute_qty_remaining(self):
      for line in self:
          line.qty_remaining = line.qty_sold - line.qty_returned_prev - line.qty

  @api.depends(
      "qty",
      "price_unit",
      "discount",
      "tax_ids",
      "product_id",
      "return_id.original_order_id.fiscal_position_id",
  )
  def _compute_amounts(self):
      for line in self:
          price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
          subtotal = price * line.qty
          tax_amount = 0.0
          total = subtotal
          if line.tax_ids:
              order = line.return_id.original_order_id
              fiscal_position = order.fiscal_position_id if order else False
              tax_ids = (
                  fiscal_position.map_tax(line.tax_ids)
                  if fiscal_position
                  else line.tax_ids
              )
              taxes = tax_ids.compute_all(
                  price,
                  currency=line.currency_id,
                  quantity=line.qty,
                  product=line.product_id,
                  partner=line.return_id.partner_id,
              )
              tax_amount = sum(t.get("amount", 0.0) for t in taxes.get("taxes", []))
              subtotal = taxes.get("total_excluded", subtotal)
              total = taxes.get("total_included", subtotal + tax_amount)
          line.price_subtotal = subtotal
          line.price_tax = tax_amount
          line.price_total = total

  @api.onchange("original_line_id")
  def _onchange_original_line_id(self):
      if not self.original_line_id:
          return
      order_line = self.original_line_id
      self.product_id = order_line.product_id
      self.uom_id = order_line.product_uom_id
      self.qty_sold = order_line.qty
      self.price_unit = order_line.price_unit
      self.discount = order_line.discount
      self.tax_ids = order_line.tax_ids
      domain = [
          ("original_line_id", "=", order_line.id),
          ("return_id.state", "in", ("confirmed", "done")),
          ("id", "!=", self._origin.id if self._origin else 0),
      ]
      previous_lines = self.env["cb.pos.return.line"].search(domain)
      self.qty_returned_prev = sum(previous_lines.mapped("qty"))
      pack_lots = order_line.pack_lot_ids
      if len(pack_lots) == 1 and pack_lots.lot_name:
          lot = self.env["stock.lot"].search([
              ("name", "=", pack_lots.lot_name),
              ("product_id", "=", self.product_id.id),
              "|",
              ("company_id", "=", False),
              ("company_id", "=", self.return_id.company_id.id if self.return_id else self.env.company.id),
          ], limit=1)
          if lot:
              self.lot_id = lot

  @api.constrains("qty", "qty_sold", "original_line_id", "return_id")
  def _check_qty(self):
      precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")
      for line in self:
          if float_compare(line.qty, 0.0, precision_digits=precision) <= 0:
              raise ValidationError(self.env._("Return quantity must be positive."))
          if not line.original_line_id:
              continue
          prior = line._get_cumulative_returned_qty(
              line.original_line_id.id,
              exclude_return_id=line.return_id.id if line.return_id else None,
          )
          remaining = abs(line.qty_sold) - prior
          if float_compare(line.qty, remaining, precision_digits=precision) > 0:
              raise ValidationError(
                  self.env._(
                      "Return quantity %(qty)s for %(product)s exceeds remaining "
                      "sold quantity %(remaining)s.",
                      qty=line.qty,
                      product=line.product_id.display_name,
                      remaining=remaining,
                  )
              )

  @api.constrains("original_line_id", "return_id")
  def _check_original_line_order(self):
      for line in self:
          if (
              line.original_line_id
              and line.return_id.original_order_id
              and line.original_line_id.order_id != line.return_id.original_order_id
          ):
              raise ValidationError(
                  self.env._(
                      "Original order line must belong to the return's original POS order."
                  )
              )
