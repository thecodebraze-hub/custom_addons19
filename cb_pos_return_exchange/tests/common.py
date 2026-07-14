# -*- coding: utf-8 -*-
"""Shared fixtures for cb_pos_return_exchange tests."""

import uuid

from odoo import fields
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


class CbPosReturnTestCommon(TestPoSCommon):
    """POS + return/exchange test harness."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref(
            "cb_pos_return_exchange.group_cb_pos_manager"
        )
        cls.config = cls.basic_config
        cls.config._cb_ensure_return_settings()
        settings = cls.env["cb.pos.return.config"]._get_config(
            company=cls.company, config=cls.config
        )
        if settings:
            settings.sudo().write(
                {
                    "module_enabled": True,
                    "allow_cash_refund": True,
                    "allow_partial_voucher_redemption": True,
                    "allow_multiple_voucher_usage": True,
                    "auto_validate_return_picking": True,
                    "auto_create_credit_note": True,
                    "auto_post_credit_note": False,
                    "max_refund_days": 365,
                    "require_receipt": False,
                    "require_original_invoice": False,
                    "voucher_barcode_prefix": "VCH/",
                    "return_barcode_prefix": "RET/",
                    "auto_barcode_detect": True,
                }
            )
        cls.return_api = cls.env["cb.pos.return.api"]

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.config.open_ui()
        self.pos_session = self.config.current_session_id
        self.pos_session.set_opening_control(0, None)
        self.pricelist = self.config.pricelist_id
        self.currency = self.pos_session.currency_id

        self.product_return = self.create_product(
            "CB Return Product", self.categ_basic, 50.0, 25.0
        )
        self.product_exchange = self.create_product(
            "CB Exchange Product", self.categ_basic, 80.0, 40.0
        )
        self.product_barcode = self.create_product(
            "CB Barcode Product", self.categ_basic, 15.0, 7.0
        )
        self.product_barcode.barcode = "CBTESTBAR001"
        self.adjust_inventory(
            [self.product_return, self.product_exchange, self.product_barcode],
            [100, 100, 100],
        )
        self.partner = self.customer

    def _sync_order(self, line_specs, partner=None, pos_reference=None):
        """Create a paid POS order. line_specs: [(product, qty), ...]."""
        order_data = self.create_ui_order_data(
            line_specs,
            customer=partner or self.partner,
        )
        if pos_reference:
            order_data["pos_reference"] = pos_reference
        result = self.env["pos.order"].sync_from_ui([order_data])
        order_id = result["pos.order"][0]["id"]
        return self.env["pos.order"].browse(order_id)

    def _return_payload(self, order, line_qty_pairs, refund_method="voucher", **extra):
        return {
            "order_id": order.id,
            "refund_method": refund_method,
            "has_receipt": True,
            "reason": extra.pop("reason", "Test return"),
            "lines": [
                {
                    "order_line_id": line.id,
                    "qty": qty,
                    "disposition": extra.pop("disposition", "restock"),
                }
                for line, qty in line_qty_pairs
            ],
            **extra,
        }

    def _api(self, user=None):
        if user:
            return self.return_api.with_user(user)
        return self.return_api

    def _api_validate(self, payload, user=None):
        return self._api(user).pos_validate_return(
            self.config.id, self.pos_session.id, payload
        )

    def _api_confirm(self, payload, user=None):
        return self._api(user).pos_confirm_return(
            self.config.id, self.pos_session.id, payload
        )

    def _create_return_record(self, order, qty=1.0, refund_method="voucher", complete=True):
        line = order.lines.filtered(
            lambda l: l.product_id == self.product_return
        )[:1]
        payload = self._return_payload(order, [(line, qty)], refund_method=refund_method)
        result = self._api_confirm(payload)
        self.assertTrue(result.get("success"), result.get("error"))
        return self.env["cb.pos.return"].browse(result["return_id"])

    def _create_user(self, login, groups):
        return self.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "password": login,
                "company_id": self.company.id,
                "company_ids": [(6, 0, [self.company.id])],
                "group_ids": [(6, 0, groups.ids)],
            }
        )

    def _new_uuid(self):
        return str(uuid.uuid4())
