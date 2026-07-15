# -*- coding: utf-8 -*-

from odoo import api, fields, models

from odoo.addons.shopify_connector import constants as sc_constants
from odoo.addons.shopify_connector.services.sequence_service import SequenceService


class ShopifyQueue(models.Model):
    """Asynchronous job queue for Shopify synchronization tasks."""

    _name = "shopify.queue"
    _description = "Shopify Queue"
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
        help="Shopify store instance that owns this queue job.",
    )
    company_id = fields.Many2one(
        related="instance_id.company_id",
        store=True,
        index=True,
    )
    job_type = fields.Selection(
        selection=sc_constants.JOB_TYPE_SELECTION,
        string="Job Type",
        required=True,
        index=True,
    )
    state = fields.Selection(
        selection=sc_constants.QUEUE_STATE_SELECTION,
        string="State",
        required=True,
        default=sc_constants.QUEUE_STATE_PENDING,
        index=True,
        copy=False,
    )
    payload = fields.Text(
        string="Payload",
        help="Serialized job payload processed by the sync service layer.",
    )
    attempts = fields.Integer(
        string="Attempts",
        default=0,
        help="Number of times this job has been processed.",
    )
    next_retry = fields.Datetime(
        string="Next Retry",
        index=True,
        help="Scheduled date and time for the next retry attempt.",
    )
    last_error = fields.Text(
        string="Last Error",
        help="Error message from the most recent failed attempt.",
    )

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> "ShopifyQueue":
        """Assign a sequence reference to new queue records."""
        sequence_service = SequenceService(self.env)
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = sequence_service.next_queue_reference()
        return super().create(vals_list)

    @api.model
    def cron_webhook_retry(self) -> None:
        """Delegate webhook retry processing to the service layer."""
        from odoo.addons.shopify_connector.services.webhook_service import WebhookService

        WebhookService(self.env).retry_failed_jobs()
