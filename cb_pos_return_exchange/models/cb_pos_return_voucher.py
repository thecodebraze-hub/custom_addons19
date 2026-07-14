# -*- coding: utf-8 -*-
"""Return voucher instrument issued from POS returns."""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class CbPosReturnVoucher(models.Model):
  """
  POS return voucher.

  Technical name: cb.pos.return.voucher

  Customer-facing refund instrument (barcode / printable voucher) issued
  when a return is settled with voucher credit. Supports partial redemption
  and remainder voucher chaining.
  """

  _name = "cb.pos.return.voucher"
  _description = "POS Return Voucher"
  _inherit = ["mail.thread", "mail.activity.mixin"]
  _order = "create_date desc, id desc"
  _check_company_auto = True

  name = fields.Char(
      string="Voucher Number",
      required=True,
      copy=False,
      readonly=True,
      default="New",
      index=True,
      tracking=True,
  )
  barcode = fields.Char(
      string="Barcode",
      copy=False,
      index=True,
      tracking=True,
      help="Scannable code used at POS redemption.",
  )
  active = fields.Boolean(default=True)
  state = fields.Selection(
      selection=[
          ("draft", "Draft"),
          ("issued", "Issued"),
          ("partial", "Partially Redeemed"),
          ("redeemed", "Fully Redeemed"),
          ("expired", "Expired"),
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
      string="Issuing POS Configuration",
      check_company=True,
      index=True,
  )
  session_id = fields.Many2one(
      comodel_name="pos.session",
      string="Issuing POS Session",
      check_company=True,
      index=True,
  )

  return_id = fields.Many2one(
      comodel_name="cb.pos.return",
      string="Return",
      index=True,
      check_company=True,
      ondelete="set null",
      tracking=True,
  )
  exchange_id = fields.Many2one(
      comodel_name="cb.pos.exchange",
      string="Exchange",
      index=True,
      check_company=True,
      ondelete="set null",
  )
  parent_voucher_id = fields.Many2one(
      comodel_name="cb.pos.return.voucher",
      string="Parent Voucher",
      index=True,
      ondelete="set null",
      help="Original voucher when this record is a remainder voucher.",
  )
  child_voucher_ids = fields.One2many(
      comodel_name="cb.pos.return.voucher",
      inverse_name="parent_voucher_id",
      string="Remainder Vouchers",
  )

  amount = fields.Monetary(
      string="Voucher Amount",
      currency_field="currency_id",
      required=True,
      tracking=True,
  )
  amount_redeemed = fields.Monetary(
      string="Redeemed Amount",
      currency_field="currency_id",
      default=0.0,
      copy=False,
      tracking=True,
  )
  amount_remaining = fields.Monetary(
      string="Remaining Amount",
      currency_field="currency_id",
      compute="_compute_amount_remaining",
      store=True,
  )
  issue_date = fields.Datetime(
      string="Issue Date",
      default=fields.Datetime.now,
      index=True,
      copy=False,
  )
  expiry_date = fields.Datetime(
      string="Expiry Date",
      index=True,
      copy=False,
  )
  is_expired = fields.Boolean(
      string="Is Expired",
      compute="_compute_is_expired",
      store=True,
  )
  is_redeemable = fields.Boolean(
      string="Is Redeemable",
      compute="_compute_is_redeemable",
  )

  print_count = fields.Integer(
      string="Print Count",
      default=0,
      readonly=True,
      copy=False,
  )
  last_printed = fields.Datetime(
      string="Last Printed",
      readonly=True,
      copy=False,
      index=True,
  )
  printed_by = fields.Many2one(
      comodel_name="res.users",
      string="Printed By",
      readonly=True,
      copy=False,
      index=True,
  )
  barcode_image = fields.Binary(
      string="Barcode Image",
      attachment=True,
      copy=False,
  )
  note = fields.Text(string="Notes")

  redemption_order_ids = fields.Many2many(
      comodel_name="pos.order",
      relation="cb_pos_return_voucher_redemption_order_rel",
      column1="voucher_id",
      column2="order_id",
      string="Redemption Orders",
      help="POS orders where this voucher was redeemed.",
  )

  _company_name_uniq = models.Constraint(
      "UNIQUE(company_id, name)",
      "Voucher number must be unique per company.",
  )
  _amount_positive = models.Constraint(
      "CHECK(amount >= 0)",
      "Voucher amount cannot be negative.",
  )
  _amount_redeemed_valid = models.Constraint(
      "CHECK(amount_redeemed >= 0 AND amount_redeemed <= amount)",
      "Redeemed amount must be between zero and the voucher amount.",
  )
  _barcode_uniq = models.Constraint(
      "UNIQUE(barcode)",
      "Voucher barcode must be unique.",
  )
  _company_state_idx = models.Index("(company_id, state)")
  _partner_state_idx = models.Index("(partner_id, state)")

  @api.depends("amount", "amount_redeemed")
  def _compute_amount_remaining(self):
      for voucher in self:
          voucher.amount_remaining = voucher.amount - voucher.amount_redeemed

  @api.depends("expiry_date", "state")
  def _compute_is_expired(self):
      now = fields.Datetime.now()
      for voucher in self:
          voucher.is_expired = bool(
              voucher.expiry_date
              and voucher.expiry_date < now
              and voucher.state not in ("redeemed", "cancelled")
          )

  @api.depends("state", "amount_remaining", "is_expired")
  def _compute_is_redeemable(self):
      for voucher in self:
          voucher.is_redeemable = (
              voucher.state in ("issued", "partial")
              and not voucher.is_expired
              and float_compare(
                  voucher.amount_remaining,
                  0.0,
                  precision_rounding=voucher.currency_id.rounding,
              )
              > 0
          )

  @api.constrains("return_id", "company_id")
  def _check_return_company(self):
      for voucher in self:
          if voucher.return_id and voucher.return_id.company_id != voucher.company_id:
              raise ValidationError(
                  self.env._("Voucher and return must belong to the same company.")
              )

  @api.constrains("amount_redeemed", "amount", "state")
  def _check_redeemed_amount(self):
      for voucher in self:
          if (
              float_compare(
                  voucher.amount_redeemed,
                  voucher.amount,
                  precision_rounding=voucher.currency_id.rounding,
              )
              > 0
          ):
              raise ValidationError(
                  self.env._("Redeemed amount cannot exceed the voucher amount.")
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
                  .next_by_code("cb.pos.return.voucher")
              )
              if not seq:
                  raise UserError(
                      self.env._("Sequence 'cb.pos.return.voucher' is not configured.")
                  )
              vals["name"] = seq
          if not vals.get("barcode"):
              vals["barcode"] = self._cb_generate_numeric_barcode(vals["name"])
      return super().create(vals_list)

  @api.model
  def _cb_generate_numeric_barcode(self, name):
      """Build a clean, scannable numeric barcode from the voucher number.

      Retail scanners handle plain digits far more reliably than the
      alphanumeric voucher reference (e.g. ``VCH/2026/00001``), so the
      printed/redeemable barcode is a zero-padded numeric string.
      """
      digits = "".join(ch for ch in (name or "") if ch.isdigit())
      if not digits:
          # Fall back to a time-based numeric value when the reference has
          # no digits at all.
          digits = fields.Datetime.now().strftime("%y%m%d%H%M%S")
      barcode = digits.zfill(12)
      # Guarantee uniqueness in the rare case of a digit collision.
      Voucher = self.sudo()
      candidate = barcode
      suffix = 0
      while Voucher.search_count([("barcode", "=", candidate)]):
          suffix += 1
          candidate = (digits + str(suffix)).zfill(12)
      return candidate
