from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    liquor_is_liquor = fields.Boolean(
        string="Is Liquor",
        default=False,
        help="Enable liquor bottle and shot tracking for this product.",
    )
    liquor_bottle_size_ml = fields.Float(
        string="Bottle Size (ml)",
        default=750.0,
        help="Bottle capacity used when this product is opened for shot sales.",
    )
    liquor_remaining_ml = fields.Float(
        string="Remaining ML",
        compute="_compute_liquor_stock_display",
        help="Remaining balance of the active opened bottle.",
    )
    liquor_available_stock_display = fields.Char(
        string="Available Stock",
        compute="_compute_liquor_stock_display",
        help="Sealed bottle quantity plus the active opened bottle balance.",
    )
    liquor_is_shot_product = fields.Boolean(
        string="Is Shot Product",
        help="Enable when this product consumes ML from a parent full bottle.",
    )
    liquor_parent_bottle_product_id = fields.Many2one(
        "product.product",
        string="Parent Bottle Product",
        domain="[('is_storable', '=', True)]",
        help="Full bottle product consumed when this shot is sold.",
    )
    liquor_consumption_ml = fields.Float(
        string="Consumption ML",
        help="ML consumed from the parent full bottle per unit sold.",
    )

    @api.depends(
        "liquor_is_liquor",
        "product_variant_id.qty_available",
        "product_variant_id.liquor_open_bottle_ids.remaining_ml",
        "product_variant_id.liquor_open_bottle_ids.state",
        "liquor_is_shot_product",
        "liquor_parent_bottle_product_id.qty_available",
        "liquor_parent_bottle_product_id.liquor_open_bottle_ids.remaining_ml",
        "liquor_parent_bottle_product_id.liquor_open_bottle_ids.state",
    )
    def _compute_liquor_stock_display(self):
        for template in self:
            if not template.liquor_is_liquor:
                template.liquor_remaining_ml = 0.0
                template.liquor_available_stock_display = False
                continue
            product = template._liquor_display_product()
            open_bottle = product.liquor_open_bottle_ids.filtered(lambda bottle: bottle.state == "open")[:1]
            remaining_ml = open_bottle.remaining_ml if open_bottle else 0.0
            bottle_qty = product.qty_available if product else 0.0

            template.liquor_remaining_ml = remaining_ml
            template.liquor_available_stock_display = _(
                "%(bottles)s Bottles + %(ml)sml",
                bottles=template._liquor_format_qty(bottle_qty),
                ml=template._liquor_format_qty(remaining_ml),
            )

    def _liquor_display_product(self):
        self.ensure_one()
        if self.liquor_is_shot_product and self.liquor_parent_bottle_product_id:
            return self.liquor_parent_bottle_product_id
        return self.product_variant_id

    @api.model
    def _liquor_format_qty(self, value):
        value = value or 0.0
        if float(value).is_integer():
            return str(int(value))
        return f"{value:g}"

    @api.constrains("liquor_parent_bottle_product_id", "liquor_is_liquor", "liquor_is_shot_product")
    def _check_liquor_shot_configuration(self):
        for template in self:
            if not template.liquor_is_liquor:
                continue
            if template.liquor_parent_bottle_product_id.product_tmpl_id == template:
                raise ValidationError(_("A shot product cannot consume itself as the parent bottle."))
