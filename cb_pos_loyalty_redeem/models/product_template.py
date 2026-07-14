# -*- coding: utf-8 -*-

from odoo import api, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model
    def _load_pos_data_read(self, records, config):
        read_data = super()._load_pos_data_read(records, config)
        if not config.cb_loyalty_redeem_enabled:
            return read_data

        redeem = config.cb_loyalty_redeem_product_id
        if not redeem:
            redeem = self.env.ref(
                "cb_pos_loyalty_redeem.product_product_loyalty_redeem",
                raise_if_not_found=False,
            )
        if not redeem:
            return read_data

        tmpl_id = redeem.product_tmpl_id.id
        product_ids_set = {product["id"] for product in read_data}
        if tmpl_id in product_ids_set:
            return read_data

        fields = self._load_pos_data_fields(config)
        product_model = self.with_context(
            {**self.env.context, "display_default_code": False}
        )
        product = product_model.search_read(
            [("id", "=", tmpl_id)],
            fields=fields,
            load=False,
        )
        read_data.extend(product)
        return read_data
