# -*- coding: utf-8 -*-
"""OAuth authentication service for Shopify store connections."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odoo.api import Environment

    from odoo.addons.shopify_connector.models.shopify_instance import ShopifyInstance
from odoo.addons.shopify_connector.services.base_service import BaseShopifyService

_logger = logging.getLogger(__name__)


class OAuthService(BaseShopifyService):
    """Service responsible for Shopify OAuth authorization flows.

    This class will handle authorization URL generation, token exchange,
    refresh-token rotation, and secure credential persistence.
    """

    def __init__(self, env: Environment, instance: ShopifyInstance) -> None:
        """Initialize the OAuth service for a Shopify store instance.

        :param env: Odoo environment used to access configuration and logging.
        :param instance: Shopify store record targeted by the OAuth flow.
        """
        super().__init__(env)
        self.instance = instance
