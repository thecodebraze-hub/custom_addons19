# -*- coding: utf-8 -*-
"""HTTP client facade for Shopify Admin API requests."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odoo.api import Environment

    from odoo.addons.shopify_connector.models.shopify_instance import ShopifyInstance
from odoo.addons.shopify_connector.services.base_service import BaseShopifyService

_logger = logging.getLogger(__name__)


class ApiClient(BaseShopifyService):
    """Facade for Shopify Admin API HTTP operations.

    This class will encapsulate authenticated requests, pagination,
    rate-limit handling, and response normalization for the connector.
    """

    def __init__(self, env: Environment, instance: ShopifyInstance) -> None:
        """Initialize the API client for a Shopify store instance.

        :param env: Odoo environment used to access configuration and logging.
        :param instance: Shopify store record providing credentials and settings.
        """
        super().__init__(env)
        self.instance = instance
