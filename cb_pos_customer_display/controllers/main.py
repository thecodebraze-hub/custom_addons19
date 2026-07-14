# -*- coding: utf-8 -*-
"""Public (token-gated) endpoints for the POS Customer Display.

The customer display page runs with ``auth="public"``, so it cannot use the
standard authenticated ``/web/dataset/call_kw`` RPC. These routes validate the
config ``access_token`` (exactly like the display page itself) and then run the
work with ``sudo``.
"""

from odoo import http
from odoo.http import request
from odoo.tools import consteq


class CbCustomerDisplayController(http.Controller):

    def _get_config(self, config_id, access_token):
        if not config_id or not access_token:
            return None
        config = request.env["pos.config"].sudo().browse(int(config_id))
        if not config.exists():
            return None
        if not consteq(access_token, config.access_token or ""):
            return None
        return config

    @http.route("/cb_pos_customer_display/search", type="json", auth="public")
    def search(self, config_id, access_token, query, **kw):
        config = self._get_config(config_id, access_token)
        if not config:
            return {"success": False, "error": "Unauthorized.", "partners": []}
        return config.cb_display_search_partners(query)

    @http.route("/cb_pos_customer_display/set_partner", type="json", auth="public")
    def set_partner(self, config_id, access_token, partner_id, **kw):
        config = self._get_config(config_id, access_token)
        if not config:
            return {"success": False, "error": "Unauthorized."}
        return config.cb_display_set_partner(int(partner_id))

    @http.route("/cb_pos_customer_display/clear_partner", type="json", auth="public")
    def clear_partner(self, config_id, access_token, **kw):
        config = self._get_config(config_id, access_token)
        if not config:
            return {"success": False}
        return config.cb_display_clear_partner()
