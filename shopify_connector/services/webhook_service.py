# -*- coding: utf-8 -*-
"""Webhook registration and validation service for Shopify events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odoo.addons.shopify_connector.services.base_service import BaseShopifyService

if TYPE_CHECKING:
    from odoo.addons.shopify_connector.models.shopify_instance import ShopifyInstance

_logger = logging.getLogger(__name__)


class WebhookService(BaseShopifyService):
    """Service responsible for Shopify webhook lifecycle management.

    This class will register webhooks with Shopify, verify HMAC signatures,
    route incoming events to queue jobs, and reconcile remote registrations.
    """

    def __init__(self, env, instance: ShopifyInstance | None = None) -> None:
        """Initialize the webhook service.

        :param env: Odoo environment used to access configuration and logging.
        :param instance: Optional Shopify store record owning webhook registrations.
        """
        super().__init__(env)
        self.instance = instance

    def retry_failed_jobs(self) -> None:
        """Retry failed webhook queue jobs."""
        _logger.info("Shopify webhook retry placeholder invoked.")
