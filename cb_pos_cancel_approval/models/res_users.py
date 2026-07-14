# -*- coding: utf-8 -*-

from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    cb_pos_manager_pin = fields.Char(
        string="POS Cancel Approval PIN",
        copy=False,
        groups="cb_pos_cancel_approval.group_cb_pos_cancel_approver,base.group_system",
        help="PIN this user enters on the POS to approve order cancellations.",
    )
