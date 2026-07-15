# -*- coding: utf-8 -*-
"""Business logic for Shopify connector sequence generation."""

from __future__ import annotations

from odoo.addons.shopify_connector import constants as sc_constants
from odoo.addons.shopify_connector.services.base_service import BaseShopifyService


class SequenceService(BaseShopifyService):
    """Generate structured references for Shopify connector records."""

    def next_log_reference(self) -> str:
        """Return the next reference for a Shopify log record."""
        return (
            self.env["ir.sequence"].next_by_code(sc_constants.SEQUENCE_CODE_LOG)
            or "New"
        )

    def next_queue_reference(self) -> str:
        """Return the next reference for a Shopify queue record."""
        return (
            self.env["ir.sequence"].next_by_code(sc_constants.SEQUENCE_CODE_QUEUE)
            or "New"
        )
