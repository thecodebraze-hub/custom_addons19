# -*- coding: utf-8 -*-

from odoo import api, fields, models

from odoo.addons.shopify_connector import constants as sc_constants
from odoo.addons.shopify_connector.services.sequence_service import SequenceService


class ShopifyLog(models.Model):
    """Persistent log entry for Shopify API and sync operations."""

    _name = "shopify.log"
    _description = "Shopify Log"
    _order = "create_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        required=True,
        readonly=True,
        copy=False,
        default="New",
        index=True,
    )
    instance_id = fields.Many2one(
        comodel_name="shopify.instance",
        string="Store",
        required=True,
        ondelete="cascade",
        index=True,
        help="Shopify store instance related to this log entry.",
    )
    company_id = fields.Many2one(
        related="instance_id.company_id",
        store=True,
        index=True,
    )
    level = fields.Selection(
        selection=sc_constants.LOG_LEVEL_SELECTION,
        string="Level",
        required=True,
        default=sc_constants.LOG_LEVEL_INFO,
        index=True,
    )
    message = fields.Text(
        string="Message",
        help="Human-readable summary of the logged event.",
    )
    request = fields.Text(
        string="Request",
        help="Raw request payload sent to Shopify.",
    )
    response = fields.Text(
        string="Response",
        help="Raw response payload received from Shopify.",
    )
    status_code = fields.Integer(
        string="Status Code",
        help="HTTP status code returned by the Shopify API.",
    )

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> "ShopifyLog":
        """Assign a sequence reference to new log records."""
        sequence_service = SequenceService(self.env)
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = sequence_service.next_log_reference()
        return super().create(vals_list)
