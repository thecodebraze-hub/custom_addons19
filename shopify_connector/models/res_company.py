# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResCompany(models.Model):
    """Extend companies with Shopify store relationships."""

    _inherit = "res.company"

    shopify_instance_ids = fields.One2many(
        comodel_name="shopify.instance",
        inverse_name="company_id",
        string="Shopify Stores",
    )
    shopify_instance_count = fields.Integer(
        compute="_compute_shopify_instance_count",
        string="Shopify Store Count",
    )

    @api.depends("shopify_instance_ids")
    def _compute_shopify_instance_count(self) -> None:
        """Count Shopify store instances linked to each company."""
        if not self:
            return
        grouped_data = self.env["shopify.instance"]._read_group(
            domain=[("company_id", "in", self.ids)],
            groupby=["company_id"],
            aggregates=["__count"],
        )
        counts_by_company = {
            company.id: count for company, count in grouped_data
        }
        for company in self:
            company.shopify_instance_count = counts_by_company.get(company.id, 0)
