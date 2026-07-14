# -*- coding: utf-8 -*-

import odoo
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosReturn(CbPosReturnTestCommon):
    def test_return_validate_and_confirm_voucher(self):
        order = self._sync_order([(self.product_return, 2)])
        line = order.lines[0]
        payload = self._return_payload(order, [(line, 1)], refund_method="voucher")

        validation = self._api_validate(payload)
        self.assertTrue(validation["success"])
        self.assertTrue(validation["valid"])
        self.assertGreater(validation["amount_total"], 0)

        result = self._api_confirm(payload)
        self.assertTrue(result["success"])
        return_doc = self.env["cb.pos.return"].browse(result["return_id"])
        self.assertEqual(return_doc.state, "done")
        self.assertEqual(return_doc.refund_method, "voucher")
        self.assertTrue(return_doc.voucher_id)
        self.assertEqual(return_doc.voucher_id.state, "issued")

    def test_return_cash_refund(self):
        order = self._sync_order([(self.product_return, 1)])
        payload = self._return_payload(
            order, [(order.lines[0], 1)], refund_method="cash"
        )
        result = self._api_confirm(payload)
        self.assertTrue(result["success"])
        return_doc = self.env["cb.pos.return"].browse(result["return_id"])
        self.assertEqual(return_doc.refund_method, "cash")
        self.assertEqual(return_doc.state, "done")

    def test_return_cancel_from_confirmed(self):
        order = self._sync_order([(self.product_return, 2)])
        line = order.lines[0]
        return_doc = self.env["cb.pos.return"].create(
            {
                "original_order_id": order.id,
                "config_id": self.config.id,
                "session_id": self.pos_session.id,
                "partner_id": order.partner_id.id,
                "company_id": self.company.id,
                "refund_method": "voucher",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "original_line_id": line.id,
                            "product_id": line.product_id.id,
                            "uom_id": line.product_uom_id.id,
                            "qty": 1,
                            "price_unit": line.price_unit,
                            "tax_ids": [(6, 0, line.tax_ids.ids)],
                        },
                    )
                ],
            }
        )
        return_doc.action_confirm()
        self.assertEqual(return_doc.state, "confirmed")
        return_doc.action_cancel()
        self.assertEqual(return_doc.state, "cancelled")

    def test_return_audit_trail_created(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        events = return_doc.audit_ids.mapped("event_type")
        self.assertIn("return_done", events)
        self.assertIn("order_linked", events)

    def test_return_amounts_computed(self):
        order = self._sync_order([(self.product_return, 2)])
        return_doc = self._create_return_record(order, qty=1)
        self.assertGreater(return_doc.amount_total, 0)
        self.assertEqual(len(return_doc.line_ids), 1)
        self.assertEqual(return_doc.line_ids.qty, 1)
