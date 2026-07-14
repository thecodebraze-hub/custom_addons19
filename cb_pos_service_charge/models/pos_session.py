from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        models_list = super()._load_pos_data_models(config)
        if "pos.service.charge" not in models_list:
            models_list.append("pos.service.charge")
        return models_list
