# -*- coding: utf-8 -*-

from datetime import timedelta

import odoo
from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosVoucher(CbPosReturnTestCommon):
    def test_voucher_issued_on_return_done(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        self.assertTrue(voucher)
        self.assertEqual(voucher.state, "issued")
        self.assertEqual(voucher.amount, return_doc.amount_total)
        self.assertEqual(voucher.amount_remaining, return_doc.amount_total)
        self.assertTrue(voucher.barcode)

    def test_voucher_partial_redemption(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        redeem_order = self._sync_order([(self.product_barcode, 1)])

        voucher._redeem(
            voucher.amount_remaining / 2,
            redeem_order,
            session=self.pos_session,
        )
        self.assertEqual(voucher.state, "partial")
        self.assertGreater(voucher.amount_redeemed, 0)
        self.assertGreater(voucher.amount_remaining, 0)

    def test_voucher_full_redemption(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        redeem_order = self._sync_order([(self.product_barcode, 1)])

        voucher._redeem(voucher.amount_remaining, redeem_order, session=self.pos_session)
        self.assertEqual(voucher.state, "redeemed")
        self.assertAlmostEqual(voucher.amount_remaining, 0.0, places=2)

    def test_voucher_validate_via_api(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id

        result = self.return_api.pos_validate_voucher(
            self.config.id, self.pos_session.id, voucher.barcode
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["voucher"]["valid"])

    def test_voucher_payment_validation_duplicate_block(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id

        first = self.return_api.pos_validate_voucher_payment(
            self.config.id,
            self.pos_session.id,
            voucher.barcode,
            partner_id=order.partner_id.id,
            applied_voucher_ids=[],
        )
        self.assertTrue(first["success"])

        duplicate = self.return_api.pos_validate_voucher_payment(
            self.config.id,
            self.pos_session.id,
            voucher.barcode,
            partner_id=order.partner_id.id,
            applied_voucher_ids=[voucher.id],
        )
        self.assertFalse(duplicate["success"])
        self.assertEqual(duplicate["error_code"], "duplicate_voucher")

    def test_voucher_cancel_requires_permission(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id

        cashier = self._create_user(
            "cb_voucher_cashier@test.com",
            self.env.ref("cb_pos_return_exchange.group_cb_pos_cashier"),
        )
        with self.assertRaises(AccessError):
            voucher.with_user(cashier).action_cancel_voucher()

        manager = self._create_user(
            "cb_voucher_manager@test.com",
            self.env.ref("cb_pos_return_exchange.group_cb_pos_manager"),
        )
        voucher.with_user(manager).action_cancel_voucher()
        self.assertEqual(voucher.state, "cancelled")

    def test_voucher_expiry_cron(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        voucher.write(
            {
                "expiry_date": fields.Datetime.now() - timedelta(days=1),
                "state": "issued",
            }
        )
        self.env["cb.pos.return.voucher"]._cron_expire_vouchers()
        self.assertEqual(voucher.state, "expired")
