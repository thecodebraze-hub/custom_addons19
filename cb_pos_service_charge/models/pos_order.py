from odoo import fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    service_charge_rate = fields.Float(
        string="Service Charge (%)",
        readonly=True,
        copy=False,
    )
    service_charge_amount = fields.Monetary(
        string="Service Charge Amount",
        currency_field="currency_id",
        readonly=True,
        copy=False,
    )
