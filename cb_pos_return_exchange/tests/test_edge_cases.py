# -*- coding: utf-8 -*-

import odoo
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosReturnEdgeCases(CbPosReturnTestCommon):
    def test_confirm_return_idempotent_uuid(self):
        order = self._sync_order([(self.product_return, 2)])
        client_uuid = self._new_uuid()
        payload = self._return_payload(
            order, [(order.lines[0], 1)], client_uuid=client_uuid
        )

        first = self._api_confirm(payload)
        self.assertTrue(first["success"])
        second = self._api_confirm(payload)
        self.assertTrue(second["success"])
        self.assertTrue(second.get("duplicate"))

    def test_return_qty_exceeds_remaining(self):
        order = self._sync_order([(self.product_return, 1)])
        payload = self._return_payload(order, [(order.lines[0], 5)])

        result = self._api_validate(payload)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "validation_failed")

    def test_return_zero_qty_rejected(self):
        order = self._sync_order([(self.product_return, 1)])
        payload = self._return_payload(order, [(order.lines[0], 0)])

        result = self._api_validate(payload)
        self.assertFalse(result["success"])

    def test_return_no_lines_rejected(self):
        order = self._sync_order([(self.product_return, 1)])
        result = self._api_validate({"order_id": order.id, "lines": []})
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "no_lines")

    def test_cash_refund_disabled_in_settings(self):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.write({"allow_cash_refund": False})

        order = self._sync_order([(self.product_return, 1)])
        payload = self._return_payload(
            order, [(order.lines[0], 1)], refund_method="cash"
        )
        result = self._api_validate(payload)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "cash_refund_disabled")
        settings.write({"allow_cash_refund": True})

    def test_multiple_voucher_usage_disabled(self):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.write({"allow_multiple_voucher_usage": False})

        order1 = self._sync_order([(self.product_return, 1)])
        return1 = self._create_return_record(order1)
        order2 = self._sync_order([(self.product_return, 1)])
        return2 = self._create_return_record(order2)

        result = self.return_api.pos_validate_voucher_payment(
            self.config.id,
            self.pos_session.id,
            return2.voucher_id.barcode,
            applied_voucher_ids=[return1.voucher_id.id],
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "multiple_vouchers_not_allowed")
        settings.write({"allow_multiple_voucher_usage": True})

    def test_partial_voucher_redemption_disabled(self):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.write({"allow_partial_voucher_redemption": False})

        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        redeem_order = self._sync_order([(self.product_barcode, 1)])

        from odoo.exceptions import UserError

        with self.assertRaises(UserError):
            voucher._redeem(
                voucher.amount_remaining / 2,
                redeem_order,
                session=self.pos_session,
            )
        settings.write({"allow_partial_voucher_redemption": True})

    def test_require_receipt_setting(self):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.write({"require_receipt": True})

        order = self._sync_order([(self.product_return, 1)])
        line = order.lines[0]
        return_doc = self.env["cb.pos.return"].create(
            {
                "original_order_id": order.id,
                "config_id": self.config.id,
                "session_id": self.pos_session.id,
                "partner_id": order.partner_id.id,
                "company_id": self.company.id,
                "refund_method": "voucher",
                "has_receipt": False,
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
        with self.assertRaises(ValidationError):
            return_doc.action_confirm()
        settings.write({"require_receipt": False})

    def test_voucher_redeem_exceeds_balance(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        redeem_order = self._sync_order([(self.product_barcode, 1)])

        with self.assertRaises(ValidationError):
            voucher._redeem(
                voucher.amount_remaining + 100,
                redeem_order,
                session=self.pos_session,
            )

    def test_completed_return_cannot_cancel(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        with self.assertRaises(ValidationError):
            return_doc.action_cancel()

    def test_sales_return_analysis_view(self):
        order = self._sync_order([(self.product_return, 1)])
        self._create_return_record(order)
        analysis = self.env["cb.pos.sales.return.analysis"].search(
            [("config_id", "=", self.config.id)], limit=5
        )
        self.assertTrue(analysis)
