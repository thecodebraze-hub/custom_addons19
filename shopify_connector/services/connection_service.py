# -*- coding: utf-8 -*-
"""Business logic for Shopify store connection management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from odoo.addons.shopify_connector.services.base_service import BaseShopifyService

if TYPE_CHECKING:
    from odoo.addons.shopify_connector.models.shopify_instance import ShopifyInstance

_logger = logging.getLogger(__name__)


class ConnectionService(BaseShopifyService):
    """Manage Shopify store connection lifecycle operations.

    This service will orchestrate OAuth authorization, token persistence,
    credential validation, and connection status updates.
    """

    def connect(self, instance: ShopifyInstance) -> bool:
        """Initiate the Shopify OAuth connection flow.

        :param instance: Shopify store record to connect.
        :return: ``True`` when the placeholder action completes successfully.
        """
        instance.ensure_one()
        _logger.info(
            "Connect requested for Shopify instance %s (id=%s).",
            instance.name,
            instance.id,
        )
        return True

    def disconnect(self, instance: ShopifyInstance) -> bool:
        """Revoke the Shopify connection and clear authentication tokens.

        :param instance: Shopify store record to disconnect.
        :return: ``True`` when the placeholder action completes successfully.
        """
        instance.ensure_one()
        _logger.info(
            "Disconnect requested for Shopify instance %s (id=%s).",
            instance.name,
            instance.id,
        )
        return True

    def test_connection(self, instance: ShopifyInstance) -> bool:
        """Validate credentials and update the connection status.

        :param instance: Shopify store record to validate.
        :return: ``True`` when the placeholder action completes successfully.
        """
        instance.ensure_one()
        _logger.info(
            "Connection test requested for Shopify instance %s (id=%s).",
            instance.name,
            instance.id,
        )
        return True
