# -*- coding: utf-8 -*-

import odoo
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosReturnAccounting(CbPosReturnTestCommon):
    def test_accounting_skipped_without_invoice(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        self.assertFalse(return_doc.original_invoice_id)
        self.assertIn(return_doc.accounting_state, ("none", "skipped"))

    def test_accounting_credit_note_on_invoiced_order(self):
        order_data = self.create_ui_order_data(
            [(self.product_return, 1)],
            customer=self.partner,
            is_invoiced=True,
        )
        result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(result["pos.order"][0]["id"])
        self.assertTrue(order.account_move)
        invoice = order.account_move
        if invoice.state != "posted":
            invoice.action_post()

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
        return_doc.action_done()

        self.assertTrue(return_doc.original_invoice_id)
        if return_doc._should_create_credit_note():
            self.assertTrue(return_doc.account_move_id)
            self.assertEqual(return_doc.account_move_id.move_type, "out_refund")
            self.assertEqual(return_doc.accounting_state, "posted")

    def test_accounting_auto_create_disabled(self):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.write({"auto_create_credit_note": False})

        order_data = self.create_ui_order_data(
            [(self.product_return, 1)],
            customer=self.partner,
            is_invoiced=True,
        )
        result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(result["pos.order"][0]["id"])
        if order.account_move and order.account_move.state != "posted":
            order.account_move.action_post()

        return_doc = self._create_return_record(order)
        self.assertFalse(return_doc._should_create_credit_note())

        settings.write({"auto_create_credit_note": True})
