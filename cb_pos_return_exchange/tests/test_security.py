# -*- coding: utf-8 -*-

import odoo
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosReturnSecurity(CbPosReturnTestCommon):
    def test_cashier_cannot_confirm_return_without_permission(self):
        pos_user = self._create_user(
            "cb_pos_only@test.com",
            self.env.ref("point_of_sale.group_pos_user"),
        )
        order = self._sync_order([(self.product_return, 1)])
        payload = self._return_payload(order, [(order.lines[0], 1)])

        result = self._api_confirm(payload, user=pos_user)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "permission_denied")

    def test_cashier_can_confirm_return_with_role(self):
        cashier = self._create_user(
            "cb_cashier@test.com",
            self.env.ref("cb_pos_return_exchange.group_cb_pos_cashier"),
        )
        order = self._sync_order([(self.product_return, 1)])
        payload = self._return_payload(order, [(order.lines[0], 1)])

        result = self._api_confirm(payload, user=cashier)
        self.assertTrue(result["success"])

    def test_cashier_cannot_cash_refund(self):
        cashier = self._create_user(
            "cb_cashier_nocash@test.com",
            self.env.ref("cb_pos_return_exchange.group_cb_pos_cashier"),
        )
        order = self._sync_order([(self.product_return, 1)])
        payload = self._return_payload(
            order, [(order.lines[0], 1)], refund_method="cash"
        )
        result = self._api_validate(payload, user=cashier)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "permission_denied")

    def test_manager_can_modify_settings(self):
        manager = self._create_user(
            "cb_settings_mgr@test.com",
            self.env.ref("cb_pos_return_exchange.group_cb_pos_manager"),
        )
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        settings.with_user(manager).write({"max_refund_days": 45})
        self.assertEqual(settings.max_refund_days, 45)

    def test_cashier_cannot_modify_settings(self):
        cashier = self._create_user(
            "cb_settings_cashier@test.com",
            self.env.ref("cb_pos_return_exchange.group_cb_pos_cashier"),
        )
        settings = self.env["cb.pos.return.config"]._get_config(
            company=self.company, config=self.config
        )
        with self.assertRaises(AccessError):
            settings.with_user(cashier).write({"max_refund_days": 10})

    def test_multi_company_return_isolation(self):
        other_company = self.setup_other_company()
        other_config = self.env["pos.config"].search(
            [("company_id", "=", other_company["company"].id)], limit=1
        )
        if not other_config:
            return

        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        returns_other = self.env["cb.pos.return"].with_company(
            other_company["company"]
        ).search([("id", "=", return_doc.id)])
        self.assertFalse(returns_other)

    def test_voucher_cashier_cannot_see_cancelled(self):
        order = self._sync_order([(self.product_return, 1)])
        return_doc = self._create_return_record(order)
        voucher = return_doc.voucher_id
        voucher.write({"state": "cancelled"})

        cashier = self._create_user(
            "cb_voucher_read@test.com",
            self.env.ref("cb_pos_return_exchange.group_cb_pos_cashier"),
        )
        visible = self.env["cb.pos.return.voucher"].with_user(cashier).search(
            [("id", "=", voucher.id)]
        )
        self.assertFalse(visible)
