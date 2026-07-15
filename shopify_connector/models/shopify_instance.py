# -*- coding: utf-8 -*-

from typing import Any

from odoo import _, api, fields, models

from odoo.addons.shopify_connector import constants as sc_constants
from odoo.addons.shopify_connector.services.connection_service import ConnectionService


class ShopifyInstance(models.Model):
    """Configuration record for a single Shopify store connection."""

    _name = "shopify.instance"
    _description = "Shopify Store"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name, id"
    _check_company_auto = True

    name = fields.Char(
        string="Store Name",
        required=True,
        tracking=True,
        help="Internal label used inside Odoo to identify this Shopify store.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
        help="Odoo company that owns this Shopify store configuration.",
    )
    store_url = fields.Char(
        string="Store URL",
        required=True,
        tracking=True,
        help="Shopify store URL, for example my-brand.myshopify.com.",
    )
    client_id = fields.Char(
        string="Client ID",
        copy=False,
        groups="shopify_connector.group_shopify_manager",
        help="OAuth client identifier from the Shopify custom app.",
    )
    client_secret = fields.Char(
        string="Client Secret",
        copy=False,
        groups="shopify_connector.group_shopify_manager",
        help="OAuth client secret from the Shopify custom app.",
    )
    access_token = fields.Char(
        string="Access Token",
        copy=False,
        groups="shopify_connector.group_shopify_manager",
        help="Admin API access token for the Shopify store.",
    )
    refresh_token = fields.Char(
        string="Refresh Token",
        copy=False,
        groups="shopify_connector.group_shopify_manager",
        help="OAuth refresh token used to renew the access token.",
    )
    webhook_secret = fields.Char(
        string="Webhook Secret",
        copy=False,
        groups="shopify_connector.group_shopify_manager",
        help="Shared secret used to verify incoming Shopify webhook signatures.",
    )
    api_version = fields.Selection(
        selection=[
            (version, version) for version in sc_constants.SHOPIFY_API_VERSIONS
        ],
        string="API Version",
        required=True,
        default=sc_constants.DEFAULT_API_VERSION,
        tracking=True,
        help="Shopify Admin API version used for REST and GraphQL requests.",
    )
    connection_status = fields.Selection(
        selection=sc_constants.CONNECTION_STATUS_SELECTION,
        string="Connection Status",
        default=sc_constants.CONNECTION_STATUS_DISCONNECTED,
        required=True,
        tracking=True,
        copy=False,
        help="Current connection state between Odoo and the Shopify store.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        tracking=True,
        help="Inactive stores are hidden from sync operations and selection lists.",
    )
    last_sync = fields.Datetime(
        string="Last Sync",
        readonly=True,
        copy=False,
        help="Date and time when the store was last synchronized.",
    )
    notes = fields.Text(
        string="Notes",
        help="Internal notes about this Shopify store configuration.",
    )
    log_ids = fields.One2many(
        comodel_name="shopify.log",
        inverse_name="instance_id",
        string="Logs",
    )
    queue_ids = fields.One2many(
        comodel_name="shopify.queue",
        inverse_name="instance_id",
        string="Queue Jobs",
    )
    webhook_ids = fields.One2many(
        comodel_name="shopify.webhook",
        inverse_name="instance_id",
        string="Webhooks",
    )
    log_count = fields.Integer(compute="_compute_related_counts")
    queue_count = fields.Integer(compute="_compute_related_counts")
    webhook_count = fields.Integer(compute="_compute_related_counts")

    _store_url_company_unique = models.Constraint(
        "unique(company_id, store_url)",
        "A Shopify store with this URL already exists for the selected company.",
    )

    @api.depends("log_ids", "queue_ids", "webhook_ids")
    def _compute_related_counts(self) -> None:
        """Compute related record counters displayed on the form view."""
        if not self:
            return
        log_counts = {
            instance.id: count
            for instance, count in self.env["shopify.log"]._read_group(
                domain=[("instance_id", "in", self.ids)],
                groupby=["instance_id"],
                aggregates=["__count"],
            )
        }
        queue_counts = {
            instance.id: count
            for instance, count in self.env["shopify.queue"]._read_group(
                domain=[("instance_id", "in", self.ids)],
                groupby=["instance_id"],
                aggregates=["__count"],
            )
        }
        webhook_counts = {
            instance.id: count
            for instance, count in self.env["shopify.webhook"]._read_group(
                domain=[("instance_id", "in", self.ids)],
                groupby=["instance_id"],
                aggregates=["__count"],
            )
        }
        for instance in self:
            instance.log_count = log_counts.get(instance.id, 0)
            instance.queue_count = queue_counts.get(instance.id, 0)
            instance.webhook_count = webhook_counts.get(instance.id, 0)

    def action_connect(self) -> bool:
        """Initiate the Shopify OAuth connection flow."""
        self.ensure_one()
        return ConnectionService(self.env).connect(self)

    def action_disconnect(self) -> bool:
        """Revoke the Shopify connection and clear authentication tokens."""
        self.ensure_one()
        return ConnectionService(self.env).disconnect(self)

    def action_test_connection(self) -> bool:
        """Validate credentials and update the connection status."""
        self.ensure_one()
        return ConnectionService(self.env).test_connection(self)

    def action_view_logs(self) -> dict[str, Any]:
        """Open logs linked to this store instance."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Shopify Logs"),
            "res_model": "shopify.log",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id)],
            "context": {
                "default_instance_id": self.id,
            },
        }

    def action_view_queue(self) -> dict[str, Any]:
        """Open queue jobs linked to this store instance."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Shopify Queue"),
            "res_model": "shopify.queue",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id)],
            "context": {
                "default_instance_id": self.id,
            },
        }

    def action_view_webhooks(self) -> dict[str, Any]:
        """Open webhooks linked to this store instance."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Shopify Webhooks"),
            "res_model": "shopify.webhook",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id)],
            "context": {
                "default_instance_id": self.id,
            },
        }

    @api.model
    def cron_sync_products(self) -> None:
        """Delegate scheduled product synchronization to the service layer."""
        from odoo.addons.shopify_connector.services.sync_service import SyncService

        SyncService(self.env).sync_products()

    @api.model
    def cron_sync_customers(self) -> None:
        """Delegate scheduled customer synchronization to the service layer."""
        from odoo.addons.shopify_connector.services.sync_service import SyncService

        SyncService(self.env).sync_customers()

    @api.model
    def cron_sync_orders(self) -> None:
        """Delegate scheduled order synchronization to the service layer."""
        from odoo.addons.shopify_connector.services.sync_service import SyncService

        SyncService(self.env).sync_orders()

    @api.model
    def cron_sync_inventory(self) -> None:
        """Delegate scheduled inventory synchronization to the service layer."""
        from odoo.addons.shopify_connector.services.sync_service import SyncService

        SyncService(self.env).sync_inventory()
