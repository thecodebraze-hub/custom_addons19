from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_iface_service_charge = fields.Boolean(
        related="pos_config_id.iface_service_charge",
        readonly=False,
    )
    pos_service_charge_id = fields.Many2one(
        related="pos_config_id.service_charge_id",
        readonly=False,
    )
