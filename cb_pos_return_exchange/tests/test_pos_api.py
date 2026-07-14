# -*- coding: utf-8 -*-

import odoo
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosApi(CbPosReturnTestCommon):
    def test_pos_get_settings(self):
        result = self.return_api.pos_get_settings(
            self.config.id, self.pos_session.id
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["settings"]["module_enabled"])
        self.assertTrue(result["permissions"]["create_return"])

    def test_pos_find_order_by_reference(self):
        order = self._sync_order(
            [(self.product_return, 1)], pos_reference="CB-FIND-001"
        )
        result = self.return_api.pos_find_order(
            self.config.id, self.pos_session.id, "CB-FIND-001"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["order"]["id"], order.id)

    def test_pos_find_product_by_barcode(self):
        result = self.return_api.pos_find_product(
            self.config.id,
            self.pos_session.id,
            barcode=self.product_barcode.barcode,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["product"]["id"], self.product_barcode.id)

    def test_pos_return_history(self):
        order = self._sync_order([(self.product_return, 1)])
        self._create_return_record(order)
        result = self.return_api.pos_return_history(
            self.config.id, self.pos_session.id, order_id=order.id
        )
        self.assertTrue(result["success"])
        self.assertGreaterEqual(len(result.get("returns", [])), 1)

    def test_pos_customer_returns(self):
        order = self._sync_order([(self.product_return, 1)])
        self._create_return_record(order)
        result = self.return_api.pos_customer_returns(
            self.config.id,
            self.pos_session.id,
            order.partner_id.id,
        )
        self.assertTrue(result["success"])
        self.assertGreaterEqual(len(result.get("returns", [])), 1)

    def test_pos_redeem_voucher(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        redeem_order = self._sync_order([(self.product_barcode, 1)])

        result = self.return_api.pos_redeem_voucher(
            self.config.id,
            self.pos_session.id,
            voucher.barcode,
            min(voucher.amount_remaining, 10.0),
            redeem_order.id,
        )
        self.assertTrue(result["success"])
        self.assertGreater(result.get("amount_redeemed", 0), 0)

    def test_pos_generate_voucher(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        result = self.return_api.pos_generate_voucher(
            self.config.id, self.pos_session.id, return_doc.id
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["voucher"]["id"], return_doc.voucher_id.id)

    def test_module_disabled_blocks_api(self):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.write({"module_enabled": False})
        result = self.return_api.pos_find_order(
            self.config.id, self.pos_session.id, "ANY"
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "module_disabled")
        settings.write({"module_enabled": True})
