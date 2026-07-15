# -*- coding: utf-8 -*-

from odoo import fields, models


class ShopifyWebhook(models.Model):
    """Registered Shopify webhook endpoint for a store instance."""

    _name = "shopify.webhook"
    _description = "Shopify Webhook"
    _order = "topic, id"
    _rec_name = "name"

    name = fields.Char(
        string="Name",
        required=True,
        help="Internal label for this webhook registration.",
    )
    instance_id = fields.Many2one(
        comodel_name="shopify.instance",
        string="Store",
        required=True,
        ondelete="cascade",
        index=True,
        help="Shopify store instance that owns this webhook.",
    )
    company_id = fields.Many2one(
        related="instance_id.company_id",
        store=True,
        index=True,
    )
    topic = fields.Char(
        string="Topic",
        required=True,
        index=True,
        help="Shopify webhook topic, for example orders/create.",
    )
    webhook_id = fields.Char(
        string="Webhook ID",
        copy=False,
        help="Identifier assigned by Shopify after webhook registration.",
    )
    secret = fields.Char(
        string="Secret",
        copy=False,
        groups="shopify_connector.group_shopify_manager",
        help="Secret used to validate webhook payloads for this topic.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Inactive webhooks are ignored by the webhook service layer.",
    )
