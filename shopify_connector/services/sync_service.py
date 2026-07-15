# -*- coding: utf-8 -*-
"""Business logic for scheduled Shopify synchronization jobs."""

from __future__ import annotations

import logging

from odoo.addons.shopify_connector.services.base_service import BaseShopifyService

_logger = logging.getLogger(__name__)


class SyncService(BaseShopifyService):
    """Coordinate scheduled synchronization between Odoo and Shopify.

    This service will enqueue and process product, customer, order, and
    inventory synchronization jobs through the queue infrastructure.
    """

    def sync_products(self) -> None:
        """Run the scheduled product synchronization placeholder."""
        _logger.info("Shopify product sync placeholder invoked.")

    def sync_customers(self) -> None:
        """Run the scheduled customer synchronization placeholder."""
        _logger.info("Shopify customer sync placeholder invoked.")

    def sync_orders(self) -> None:
        """Run the scheduled order synchronization placeholder."""
        _logger.info("Shopify order sync placeholder invoked.")

    def sync_inventory(self) -> None:
        """Run the scheduled inventory synchronization placeholder."""
        _logger.info("Shopify inventory sync placeholder invoked.")
