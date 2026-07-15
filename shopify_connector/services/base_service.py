# -*- coding: utf-8 -*-
"""Base class for Shopify Connector service layer objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from odoo.api import Environment


class BaseShopifyService:
    """Provide shared access to the Odoo environment for all services."""

    def __init__(self, env: Environment) -> None:
        """Initialize the service with an Odoo environment.

        :param env: Active Odoo environment bound to the current transaction.
        """
        self.env = env
