# -*- coding: utf-8 -*-

import odoo
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosExchange(CbPosReturnTestCommon):
    def test_exchange_complete_with_customer_payment(self):
        original = self._sync_order([(self.product_return, 1)])
        line = original.lines[0]
        return_doc = self.env["cb.pos.return"].create(
            {
                "original_order_id": original.id,
                "config_id": self.config.id,
                "session_id": self.pos_session.id,
                "partner_id": original.partner_id.id,
                "company_id": self.company.id,
                "refund_method": "exchange",
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
        replacement = self._sync_order([(self.product_exchange, 1)])

        exchange = self.env["cb.pos.exchange"].create(
            {
                "return_id": return_doc.id,
                "replacement_order_id": replacement.id,
                "partner_id": return_doc.partner_id.id,
                "company_id": self.company.id,
                "config_id": self.config.id,
                "session_id": self.pos_session.id,
                "customer_payment": max(
                    0.0, replacement.amount_total - return_doc.amount_total
                ),
            }
        )
        exchange.action_complete()

        self.assertEqual(exchange.state, "done")
        self.assertEqual(return_doc.state, "done")
        self.assertGreater(exchange.amount_return, 0)
        self.assertGreater(exchange.amount_replacement, 0)

    def test_exchange_via_pos_api(self):
        original = self._sync_order([(self.product_return, 1)])
        line = original.lines[0]
        return_doc = self.env["cb.pos.return"].create(
            {
                "original_order_id": original.id,
                "config_id": self.config.id,
                "session_id": self.pos_session.id,
                "partner_id": original.partner_id.id,
                "company_id": self.company.id,
                "refund_method": "exchange",
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
        replacement = self._sync_order([(self.product_exchange, 1)])
        result = self.env["cb.pos.exchange"].pos_create_exchange(
            {
                "return_id": return_doc.id,
                "replacement_order_id": replacement.id,
                "customer_payment": max(
                    0.0, replacement.amount_total - return_doc.amount_total
                ),
                "auto_complete": True,
            },
            self.config.id,
            self.pos_session.id,
        )
        self.assertTrue(result.get("id"))
        exchange = self.env["cb.pos.exchange"].browse(result["id"])
        self.assertEqual(exchange.state, "done")

    def test_exchange_settlement_balanced(self):
        original = self._sync_order([(self.product_return, 2)])
        line = original.lines[0]
        return_doc = self.env["cb.pos.return"].create(
            {
                "original_order_id": original.id,
                "config_id": self.config.id,
                "session_id": self.pos_session.id,
                "partner_id": original.partner_id.id,
                "company_id": self.company.id,
                "refund_method": "exchange",
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
        replacement = self._sync_order([(self.product_return, 1)])
        exchange = self.env["cb.pos.exchange"].create(
            {
                "return_id": return_doc.id,
                "replacement_order_id": replacement.id,
                "partner_id": return_doc.partner_id.id,
                "company_id": self.company.id,
                "config_id": self.config.id,
                "session_id": self.pos_session.id,
                "customer_payment": 0.0,
            }
        )
        exchange.action_complete()
        self.assertEqual(exchange.state, "done")
