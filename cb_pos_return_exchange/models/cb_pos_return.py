# -*- coding: utf-8 -*-
"""POS return transaction header."""

import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class CbPosReturn(models.Model):
  """
  POS return document.

  Technical name: cb.pos.return

  Header for a product return initiated from the Point of Sale. Links the
  original sale order, returned line items, refund settlement, stock moves,
  and optional exchange or voucher issuance.
  """

  _name = "cb.pos.return"
  _description = "POS Return"
  _inherit = ["mail.thread", "mail.activity.mixin"]
  _order = "create_date desc, id desc"
  _check_company_auto = True

  name = fields.Char(
      string="Reference",
      required=True,
      copy=False,
      readonly=True,
      default="New",
      index=True,
      tracking=True,
  )
  active = fields.Boolean(default=True)
  uuid = fields.Char(
      string="POS UUID",
      copy=False,
      index=True,
      help="Client-side idempotency key for offline POS synchronization.",
  )
  state = fields.Selection(
      selection=[
          ("draft", "Draft"),
          ("confirmed", "Confirmed"),
          ("done", "Done"),
          ("cancelled", "Cancelled"),
      ],
      string="Status",
      default="draft",
      required=True,
      index=True,
      tracking=True,
      copy=False,
  )
  partner_id = fields.Many2one(
      comodel_name="res.partner",
      string="Customer",
      index=True,
      tracking=True,
      check_company=True,
  )
  company_id = fields.Many2one(
      comodel_name="res.company",
      string="Company",
      required=True,
      default=lambda self: self.env.company,
      index=True,
  )
  currency_id = fields.Many2one(
      comodel_name="res.currency",
      string="Currency",
      required=True,
      default=lambda self: self.env.company.currency_id,
  )
  config_id = fields.Many2one(
      comodel_name="pos.config",
      string="POS Configuration",
      required=True,
      check_company=True,
      index=True,
  )
  session_id = fields.Many2one(
      comodel_name="pos.session",
      string="POS Session",
      index=True,
      check_company=True,
  )
  cashier_id = fields.Many2one(
      comodel_name="res.users",
      string="Cashier",
      default=lambda self: self.env.user,
      index=True,
  )
  manager_id = fields.Many2one(
      comodel_name="res.users",
      string="Manager",
      index=True,
      tracking=True,
  )

  original_order_id = fields.Many2one(
      comodel_name="pos.order",
      string="Original POS Order",
      required=True,
      index=True,
      check_company=True,
      tracking=True,
  )
  return_order_id = fields.Many2one(
      comodel_name="pos.order",
      string="Return POS Order",
      index=True,
      check_company=True,
      copy=False,
      tracking=True,
      help="Refund order created in POS for this return.",
  )
  original_payment_ids = fields.Many2many(
      comodel_name="pos.payment",
      relation="cb_pos_return_original_payment_rel",
      column1="return_id",
      column2="payment_id",
      string="Original Payments",
      help="Payments from the original sale referenced for reversal or refund.",
  )
  refund_method = fields.Selection(
      selection=[
          ("cash", "Cash"),
          ("card", "Card"),
          ("original_payment", "Original Payment Method"),
          ("voucher", "Return Voucher"),
          ("store_credit", "Store Credit"),
          ("exchange", "Exchange"),
          ("mixed", "Mixed"),
      ],
      string="Refund Method",
      required=True,
      default="voucher",
      index=True,
      tracking=True,
  )
  reason = fields.Char(string="Return Reason", tracking=True)
  has_receipt = fields.Boolean(
      string="Has Receipt",
      default=True,
      help="Whether the customer presented the original sales receipt.",
  )
  note = fields.Text(string="Notes")

  line_ids = fields.One2many(
      comodel_name="cb.pos.return.line",
      inverse_name="return_id",
      string="Return Lines",
      copy=True,
  )
  voucher_ids = fields.One2many(
      comodel_name="cb.pos.return.voucher",
      inverse_name="return_id",
      string="Vouchers",
      copy=False,
  )
  voucher_id = fields.Many2one(
      comodel_name="cb.pos.return.voucher",
      string="Primary Voucher",
      index=True,
      copy=False,
      check_company=True,
      help="Main voucher issued for this return settlement.",
  )
  exchange_id = fields.Many2one(
      comodel_name="cb.pos.exchange",
      string="Exchange",
      index=True,
      copy=False,
      check_company=True,
  )

  picking_id = fields.Many2one(
      comodel_name="stock.picking",
      string="Stock Picking",
      index=True,
      copy=False,
      check_company=True,
  )
  account_move_id = fields.Many2one(
      comodel_name="account.move",
      string="Accounting Entry",
      index=True,
      copy=False,
      check_company=True,
  )

  line_count = fields.Integer(
      string="Line Count",
      compute="_compute_line_count",
      store=True,
  )
  amount_untaxed = fields.Monetary(
      string="Untaxed Amount",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
  )
  amount_tax = fields.Monetary(
      string="Tax Amount",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
  )
  amount_total = fields.Monetary(
      string="Total Amount",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
      tracking=True,
  )
  days_since_sale = fields.Integer(
      string="Days Since Sale",
      compute="_compute_days_since_sale",
      store=True,
  )
  voucher_count = fields.Integer(
      string="Voucher Count",
      compute="_compute_voucher_count",
  )
  has_exchange = fields.Boolean(
      string="Has Exchange",
      compute="_compute_has_exchange",
      store=True,
  )

  _company_name_uniq = models.Constraint(
      "UNIQUE(company_id, name)",
      "Return reference must be unique per company.",
  )
  _uuid_uniq = models.Constraint(
      "UNIQUE(uuid)",
      "Return POS UUID must be unique.",
  )
  _company_state_idx = models.Index("(company_id, state)")
  _original_order_state_idx = models.Index("(original_order_id, state)")

  @api.depends("line_ids")
  def _compute_line_count(self):
      for record in self:
          record.line_count = len(record.line_ids)

  @api.depends(
      "line_ids.price_subtotal",
      "line_ids.price_tax",
      "line_ids.price_total",
  )
  def _compute_amounts(self):
      for record in self:
          record.amount_untaxed = sum(record.line_ids.mapped("price_subtotal"))
          record.amount_tax = sum(record.line_ids.mapped("price_tax"))
          record.amount_total = sum(record.line_ids.mapped("price_total"))

  @api.depends("original_order_id", "original_order_id.date_order")
  def _compute_days_since_sale(self):
      now = fields.Datetime.now()
      for record in self:
          order_date = record.original_order_id.date_order
          if not order_date:
              record.days_since_sale = 0
              continue
          delta = now - order_date
          record.days_since_sale = max(delta.days, 0)

  @api.depends("voucher_ids")
  def _compute_voucher_count(self):
      for record in self:
          record.voucher_count = len(record.voucher_ids)

  @api.depends("exchange_id")
  def _compute_has_exchange(self):
      for record in self:
          record.has_exchange = bool(record.exchange_id)

  @api.constrains("original_order_id", "company_id")
  def _check_original_order_company(self):
      for record in self:
          if (
              record.original_order_id
              and record.original_order_id.company_id != record.company_id
          ):
              raise ValidationError(
                  self.env._(
                      "Original POS order must belong to the same company as the return."
                  )
              )

  @api.constrains("line_ids", "state")
  def _check_lines_required(self):
      for record in self:
          if record.state == "done" and not record.line_ids:
              raise ValidationError(
                  self.env._("A completed return must contain at least one line.")
              )

  @api.model_create_multi
  def create(self, vals_list):
      for vals in vals_list:
          company = self.env["res.company"].browse(
              vals.get("company_id") or self.env.company.id
          )
          if not vals.get("currency_id"):
              vals["currency_id"] = company.currency_id.id
          if vals.get("name", "New") == "New":
              seq = (
                  self.env["ir.sequence"]
                  .with_company(company)
                  .next_by_code("cb.pos.return")
              )
              if not seq:
                  raise UserError(
                      self.env._("Sequence 'cb.pos.return' is not configured.")
                  )
              vals["name"] = seq
          if not vals.get("uuid"):
              vals["uuid"] = str(uuid.uuid4())
      return super().create(vals_list)
