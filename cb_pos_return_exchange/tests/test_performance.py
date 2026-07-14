# -*- coding: utf-8 -*-

import time

import odoo
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange", "cb_pos_performance")
class TestCbPosReturnPerformance(CbPosReturnTestCommon):
    def test_bulk_return_search_performance(self):
        for _i in range(10):
            order = self._sync_order([(self.product_return, 2)])
            self._create_return_record(order, qty=1)

        start = time.perf_counter()
        returns = self.env["cb.pos.return"].search([("state", "=", "done")])
        elapsed = time.perf_counter() - start

        self.assertGreaterEqual(len(returns), 10)
        self.assertLess(elapsed, 2.0, "Return search took too long: %.2fs" % elapsed)

    def test_read_group_pivot_performance(self):
        for _i in range(8):
            order = self._sync_order([(self.product_return, 1)])
            self._create_return_record(order)

        start = time.perf_counter()
        groups = self.env["cb.pos.return"].read_group(
            [("state", "=", "done")],
            ["amount_total:sum", "report_count:sum"],
            ["config_id"],
            lazy=False,
        )
        elapsed = time.perf_counter() - start

        self.assertTrue(groups)
        self.assertLess(elapsed, 2.0, "read_group took too long: %.2fs" % elapsed)

    def test_api_validate_performance(self):
        order = self._sync_order([(self.product_return, 5)])
        payload = self._return_payload(order, [(order.lines[0], 1)])

        start = time.perf_counter()
        for _i in range(20):
            self._api_validate(payload)
        elapsed = time.perf_counter() - start

        self.assertLess(
            elapsed, 5.0, "20 validations took too long: %.2fs" % elapsed
        )

    def test_barcode_classify_batch_performance(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        codes = [
            self.product_barcode.barcode,
            return_doc.voucher_id.barcode,
            return_doc.name,
        ]

        start = time.perf_counter()
        for _i in range(30):
            for code in codes:
                self.return_api.pos_classify_barcode(
                    self.config.id, self.pos_session.id, code
                )
        elapsed = time.perf_counter() - start

        self.assertLess(
            elapsed, 8.0, "Barcode classification batch took too long: %.2fs" % elapsed
        )
