# -*- coding: utf-8 -*-
"""POS exchange transaction."""

import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero


class CbPosExchange(models.Model):
  """
  POS exchange document.

  Technical name: cb.pos.exchange

  Links a return leg (returned products) with a replacement sale order.
  Tracks the financial difference between returned and replacement values
  and how the exchange is settled (customer payment, voucher, or balanced).
  """

  _name = "cb.pos.exchange"
  _description = "POS Exchange"
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
  )

  return_id = fields.Many2one(
      comodel_name="cb.pos.return",
      string="Return",
      required=True,
      index=True,
      check_company=True,
      ondelete="restrict",
      tracking=True,
      help="Return leg of the exchange (products being brought back).",
  )
  replacement_order_id = fields.Many2one(
      comodel_name="pos.order",
      string="Replacement POS Order",
      index=True,
      check_company=True,
      copy=False,
      tracking=True,
      help="POS order containing the replacement products.",
  )
  voucher_ids = fields.One2many(
      comodel_name="cb.pos.return.voucher",
      inverse_name="exchange_id",
      string="Vouchers",
      copy=False,
  )
  voucher_id = fields.Many2one(
      comodel_name="cb.pos.return.voucher",
      string="Settlement Voucher",
      index=True,
      check_company=True,
      copy=False,
      help="Voucher issued or applied for the exchange difference.",
  )

  amount_return = fields.Monetary(
      string="Return Amount",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
      help="Total value of returned products.",
  )
  amount_replacement = fields.Monetary(
      string="Replacement Amount",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
      help="Total value of replacement products.",
  )
  difference_amount = fields.Monetary(
      string="Difference Amount",
      currency_field="currency_id",
      compute="_compute_amounts",
      store=True,
      help="Positive: customer pays. Negative: store owes credit/voucher.",
  )
  customer_payment = fields.Monetary(
      string="Customer Payment",
      currency_field="currency_id",
      default=0.0,
      help="Amount collected from the customer when replacement costs more.",
  )
  voucher_used = fields.Boolean(
      string="Voucher Used",
      default=False,
      help="Set when an existing voucher is applied on the exchange.",
  )
  settlement_mode = fields.Selection(
      selection=[
          ("balanced", "Balanced"),
          ("customer_payment", "Customer Payment"),
          ("voucher", "Voucher"),
          ("store_credit", "Store Credit"),
      ],
      string="Settlement Mode",
      compute="_compute_settlement_mode",
      store=True,
  )
  note = fields.Text(string="Notes")

  _company_name_uniq = models.Constraint(
      "UNIQUE(company_id, name)",
      "Exchange reference must be unique per company.",
  )
  _uuid_uniq = models.Constraint(
      "UNIQUE(uuid)",
      "Exchange POS UUID must be unique.",
  )
  _return_uniq = models.Constraint(
      "UNIQUE(return_id)",
      "Only one exchange is allowed per return.",
  )
  _customer_payment_positive = models.Constraint(
      "CHECK(customer_payment >= 0)",
      "Customer payment cannot be negative.",
  )
  _company_state_idx = models.Index("(company_id, state)")

  @api.depends(
      "return_id",
      "return_id.amount_total",
      "replacement_order_id",
      "replacement_order_id.amount_total",
  )
  def _compute_amounts(self):
      for exchange in self:
          amount_return = exchange.return_id.amount_total if exchange.return_id else 0.0
          amount_replacement = (
              exchange.replacement_order_id.amount_total
              if exchange.replacement_order_id
              else 0.0
          )
          exchange.amount_return = amount_return
          exchange.amount_replacement = amount_replacement
          exchange.difference_amount = amount_replacement - amount_return

  @api.depends("difference_amount", "voucher_used", "customer_payment", "currency_id")
  def _compute_settlement_mode(self):
      for exchange in self:
          rounding = exchange.currency_id.rounding or 0.01
          if float_is_zero(exchange.difference_amount, precision_rounding=rounding):
              exchange.settlement_mode = "balanced"
          elif exchange.difference_amount > 0:
              exchange.settlement_mode = "customer_payment"
          elif exchange.voucher_used:
              exchange.settlement_mode = "voucher"
          else:
              exchange.settlement_mode = "store_credit"

  @api.constrains("return_id", "company_id")
  def _check_return_company(self):
      for exchange in self:
          if exchange.return_id.company_id != exchange.company_id:
              raise ValidationError(
                  self.env._("Return and exchange must belong to the same company.")
              )

  @api.constrains("replacement_order_id", "return_id")
  def _check_replacement_order(self):
      for exchange in self:
          if (
              exchange.replacement_order_id
              and exchange.return_id
              and exchange.replacement_order_id.company_id != exchange.company_id
          ):
              raise ValidationError(
                  self.env._(
                      "Replacement POS order must belong to the same company as the exchange."
                  )
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
                  .next_by_code("cb.pos.exchange")
              )
              if not seq:
                  raise UserError(
                      self.env._("Sequence 'cb.pos.exchange' is not configured.")
                  )
              vals["name"] = seq
          if not vals.get("uuid"):
              vals["uuid"] = str(uuid.uuid4())
      records = super().create(vals_list)
      for exchange in records:
          if exchange.return_id and not exchange.return_id.exchange_id:
              exchange.return_id.exchange_id = exchange.id
      return records
