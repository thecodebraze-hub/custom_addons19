from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    iface_kot_print = fields.Boolean(
        string="KOT Printing",
        default=False,
        help="Print Kitchen Order Tickets on the POS receipt printer (80mm Epson, IoT Box, or browser print).",
    )
