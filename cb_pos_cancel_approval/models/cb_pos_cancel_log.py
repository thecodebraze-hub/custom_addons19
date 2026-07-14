# -*- coding: utf-8 -*-

from odoo import fields, models


class CbPosCancelApprovalLog(models.Model):
    _name = "cb.pos.cancel.approval.log"
    _description = "POS Order Cancel Approval Log"
    _order = "create_date desc"

    action_type = fields.Selection(
        selection=[
            ("cancel_order", "Cancel Order"),
            ("remove_line", "Remove Line"),
        ],
        string="Action",
        default="cancel_order",
        readonly=True,
    )
    config_id = fields.Many2one("pos.config", string="Point of Sale", readonly=True)
    session_id = fields.Many2one("pos.session", string="Session", readonly=True)
    cashier_id = fields.Many2one("res.users", string="Cashier", readonly=True)
    manager_id = fields.Many2one("res.users", string="Approved By", readonly=True)
    order_reference = fields.Char(string="Order Reference", readonly=True)
    product_name = fields.Char(string="Product", readonly=True)
    amount = fields.Monetary(currency_field="currency_id", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    reason = fields.Text(readonly=True)
