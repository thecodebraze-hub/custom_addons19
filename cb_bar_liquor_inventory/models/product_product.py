from odoo import api, fields, models, _


class ProductProduct(models.Model):
    _inherit = "product.product"

    liquor_open_bottle_ids = fields.One2many(
        "liquor.open.bottle",
        "product_id",
        string="Opened Bottles",
    )
    liquor_is_liquor = fields.Boolean(
        related="product_tmpl_id.liquor_is_liquor",
        readonly=False,
    )
    liquor_bottle_size_ml = fields.Float(
        related="product_tmpl_id.liquor_bottle_size_ml",
        readonly=False,
    )
    liquor_remaining_ml = fields.Float(
        string="Remaining ML",
        compute="_compute_liquor_stock_display",
    )
    liquor_available_stock_display = fields.Char(
        string="Available Stock",
        compute="_compute_liquor_stock_display",
    )
    liquor_is_shot_product = fields.Boolean(
        related="product_tmpl_id.liquor_is_shot_product",
        readonly=False,
    )
    liquor_parent_bottle_product_id = fields.Many2one(
        related="product_tmpl_id.liquor_parent_bottle_product_id",
        readonly=False,
    )
    liquor_consumption_ml = fields.Float(
        related="product_tmpl_id.liquor_consumption_ml",
        readonly=False,
    )

    @api.depends(
        "liquor_is_liquor",
        "qty_available",
        "liquor_open_bottle_ids.remaining_ml",
        "liquor_open_bottle_ids.state",
    )
    def _compute_liquor_stock_display(self):
        for product in self:
            if not product.liquor_is_liquor:
                product.liquor_remaining_ml = 0.0
                product.liquor_available_stock_display = False
                continue
            display_product = product
            if product.liquor_is_shot_product and product.liquor_parent_bottle_product_id:
                display_product = product.liquor_parent_bottle_product_id
            open_bottle = display_product.liquor_open_bottle_ids.filtered(lambda bottle: bottle.state == "open")[:1]
            remaining_ml = open_bottle.remaining_ml if open_bottle else 0.0
            bottle_qty = display_product.qty_available if display_product else 0.0

            product.liquor_remaining_ml = remaining_ml
            product.liquor_available_stock_display = _(
                "%(bottles)s Bottles + %(ml)sml",
                bottles=self.env["product.template"]._liquor_format_qty(bottle_qty),
                ml=self.env["product.template"]._liquor_format_qty(remaining_ml),
            )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_to_load = super()._load_pos_data_fields(config)
        return fields_to_load + [
            field
            for field in [
                "liquor_is_liquor",
                "liquor_is_shot_product",
                "liquor_parent_bottle_product_id",
                "liquor_consumption_ml",
                "liquor_available_stock_display",
            ]
            if field not in fields_to_load
        ]
