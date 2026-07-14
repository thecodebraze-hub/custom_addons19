# -*- coding: utf-8 -*-

import odoo
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosBarcode(CbPosReturnTestCommon):
    def test_classify_product_barcode(self):
        result = self.return_api.pos_classify_barcode(
            self.config.id,
            self.pos_session.id,
            self.product_barcode.barcode,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["barcode_type"], "product")
        self.assertEqual(result["product"]["id"], self.product_barcode.id)

    def test_classify_voucher_barcode(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id

        result = self.return_api.pos_classify_barcode(
            self.config.id,
            self.pos_session.id,
            voucher.barcode,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["barcode_type"], "voucher")
        self.assertEqual(result["voucher"]["id"], voucher.id)

    def test_classify_voucher_prefix(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id

        result = self.return_api.pos_classify_barcode(
            self.config.id,
            self.pos_session.id,
            "VCH/%s" % voucher.name.split("/")[-1],
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["barcode_type"], "voucher")

    def test_classify_return_document(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)

        result = self.return_api.pos_classify_barcode(
            self.config.id,
            self.pos_session.id,
            return_doc.name,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["barcode_type"], "return")
        self.assertEqual(result["return"]["id"], return_doc.id)

    def test_classify_empty_barcode(self):
        result = self.return_api.pos_classify_barcode(
            self.config.id, self.pos_session.id, ""
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "barcode_empty")

    def test_barcode_detection_disabled(self):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.write({"auto_barcode_detect": False})
        result = self.return_api.pos_classify_barcode(
            self.config.id,
            self.pos_session.id,
            self.product_barcode.barcode,
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "barcode_disabled")
        settings.write({"auto_barcode_detect": True})

    def test_detect_barcode_format_ean13(self):
        fmt = self.return_api._detect_barcode_format("5901234123457")
        self.assertEqual(fmt, "ean13")

    def test_barcode_candidates_normalization(self):
        candidates = self.return_api._barcode_candidates("  cbtestbar001 ")
        self.assertIn("CBTESTBAR001", candidates)
