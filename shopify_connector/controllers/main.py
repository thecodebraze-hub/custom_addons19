# -*- coding: utf-8 -*-
"""Public HTTP endpoints for the Shopify Connector module."""

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ShopifyController(http.Controller):
    """Expose lightweight public endpoints for connector health checks."""

    @http.route(
        "/shopify/status",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def status(self) -> http.Response:
        """Return a simple JSON health-check payload."""
        _logger.debug("Shopify status endpoint requested.")
        return request.make_json_response({"status": "ok"})
