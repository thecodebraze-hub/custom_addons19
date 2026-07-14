from odoo import api, fields, models


class PosServiceCharge(models.Model):
    _name = "pos.service.charge"
    _description = "POS Service Charge"
    _inherit = ["pos.load.mixin"]
    _order = "sequence, id"

    name = fields.Char(required=True, default="Service Charge")
    rate = fields.Float(
        string="Rate (%)",
        default=10.0,
        required=True,
        help="Default service charge percentage applied from the POS Actions menu.",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Service Charge Product",
        required=True,
        ondelete="restrict",
        help="Product line added to the POS order for the service charge amount.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _rate_bounds = models.Constraint(
        "CHECK(rate >= 0 AND rate <= 100)",
        "Service charge rate must be between 0 and 100.",
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [("company_id", "=", config.company_id.id), ("active", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "rate", "product_id"]
