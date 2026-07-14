# -*- coding: utf-8 -*-

import odoo
from odoo.tests import tagged

from .common import CbPosReturnTestCommon


@tagged("post_install", "-at_install", "cb_pos_return_exchange")
class TestCbPosReturnInventory(CbPosReturnTestCommon):
    def test_return_creates_stock_picking(self):
        order = self._sync_order([(self.product_return, 2)])
        return_doc = self._create_return_record(order, qty=1)
        self.assertTrue(return_doc.picking_ids)
        pickings = return_doc.picking_ids.filtered(
            lambda p: p.state in ("done", "assigned", "confirmed")
        )
        self.assertTrue(pickings)

    def test_return_restock_move_qty(self):
        order = self._sync_order([(self.product_return, 2)])
        return_doc = self._create_return_record(order, qty=1)
        moves = return_doc.stock_move_ids.filtered(
            lambda m: m.product_id == self.product_return
        )
        self.assertTrue(moves)
        self.assertAlmostEqual(sum(moves.mapped("product_uom_qty")), 1.0, places=2)

    def test_return_scrap_disposition(self):
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
                            "disposition": "scrap",
                        },
                    )
                ],
            }
        )
        if not self.company.scrap_location_id:
            scrap_loc = self.env["stock.location"].search(
                [("scrap_location", "=", True), ("company_id", "=", self.company.id)],
                limit=1,
            )
            if scrap_loc:
                self.company.scrap_location_id = scrap_loc.id

        return_doc.action_confirm()
        return_doc.action_done()
        self.assertEqual(return_doc.state, "done")
        self.assertTrue(return_doc.line_ids.disposition, "scrap")

    def test_returnable_qty_decreases_after_return(self):
        order = self._sync_order([(self.product_return, 2)])
        self._create_return_record(order, qty=1)

        qty_map = self.return_api._get_returnable_qty_map(
            order.lines.ids, {line.id: line.qty for line in order.lines}
        )
        line = order.lines[0]
        self.assertLess(qty_map.get(line.id, 0), line.qty)
