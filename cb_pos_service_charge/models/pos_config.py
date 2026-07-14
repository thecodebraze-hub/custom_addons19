from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    iface_service_charge = fields.Boolean(
        string="Service Charge",
        default=True,
        help="Allow cashiers to add a percentage-based service charge from the POS Actions menu.",
    )
    service_charge_id = fields.Many2one(
        "pos.service.charge",
        string="Service Charge",
        domain="[('company_id', '=', company_id)]",
        help="Default service charge configuration for this point of sale.",
    )

    @api.model
    def _assign_default_service_charge_configs(self):
        default_service_charge = self.env.ref(
            "cb_pos_service_charge.default_pos_service_charge",
            raise_if_not_found=False,
        )
        if not default_service_charge:
            return
        for config in self.search([("service_charge_id", "=", False)]):
            company_charge = default_service_charge.filtered(
                lambda sc: sc.company_id == config.company_id
            )[:1]
            config.service_charge_id = (company_charge or default_service_charge[:1]).id

    def _get_special_products(self):
        products = super()._get_special_products()
        service_product = self.env.ref(
            "cb_pos_service_charge.product_product_service_charge",
            raise_if_not_found=False,
        )
        if service_product:
            products |= service_product
        return products

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        default_service_charge = self.env.ref(
            "cb_pos_service_charge.default_pos_service_charge",
            raise_if_not_found=False,
        )
        if default_service_charge:
            for config in configs.filtered(lambda c: not c.service_charge_id):
                company_charge = default_service_charge.filtered(
                    lambda sc: sc.company_id == config.company_id
                )[:1]
                if company_charge:
                    config.service_charge_id = company_charge.id
        return configs
