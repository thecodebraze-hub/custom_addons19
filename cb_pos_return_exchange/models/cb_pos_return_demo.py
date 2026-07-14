# -*- coding: utf-8 -*-
"""Demo data loader for POS Return & Exchange."""

import logging
import uuid

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DEMO_MARKER = "demo_return_voucher_done"


class CbPosReturnDemo(models.AbstractModel):
    _name = "cb.pos.return.demo"
    _description = "POS Return & Exchange Demo Loader"

    @api.model
    def load_demo_data(self):
        """Load sample customers, orders, returns, vouchers, and exchanges."""
        if self.env.ref(
            f"cb_pos_return_exchange.{DEMO_MARKER}", raise_if_not_found=False
        ):
            _logger.info("cb_pos_return_exchange demo data already loaded, skipping.")
            return

        company = self.env.company
        env = self.env(user=self.env.ref("base.user_admin").id).sudo()

        try:
            partners = self._get_demo_partners(env)
            products = self._get_demo_products(env)
            config = self._get_or_create_pos_config(env, company)
            config._cb_ensure_return_settings()
            session = self._get_or_create_session(env, config)
            self._set_product_stock(env, products, config)

            order_alice = self._create_pos_order(
                env,
                session,
                config,
                partners["alice"],
                [(products["tee"], 2, 25.0)],
                "CB-DEMO-001",
            )
            order_bob = self._create_pos_order(
                env,
                session,
                config,
                partners["bob"],
                [(products["jeans"], 1, 59.0)],
                "CB-DEMO-002",
            )
            order_carol = self._create_pos_order(
                env,
                session,
                config,
                partners["carol"],
                [
                    (products["sneakers"], 1, 89.0),
                    (products["tee"], 1, 25.0),
                ],
                "CB-DEMO-003",
            )
            replacement_order = self._create_pos_order(
                env,
                session,
                config,
                partners["carol"],
                [(products["jeans"], 1, 59.0)],
                "CB-DEMO-004",
            )

            return_voucher = self._create_return(
                env,
                order_alice,
                session,
                refund_method="voucher",
                qty_map={products["tee"].id: 1},
                reason="Wrong size",
                complete=True,
            )
            self._register_xmlid(
                env, DEMO_MARKER, "cb.pos.return", return_voucher.id
            )

            self._create_return(
                env,
                order_bob,
                session,
                refund_method="cash",
                qty_map={products["jeans"].id: 1},
                reason="Changed mind",
                complete=True,
            )

            return_draft = self._create_return(
                env,
                order_carol,
                session,
                refund_method="voucher",
                qty_map={products["tee"].id: 1},
                reason="Demo draft return",
                complete=False,
            )

            voucher = return_voucher.voucher_id
            if voucher:
                self._register_xmlid(
                    env, "demo_voucher_issued", "cb.pos.return.voucher", voucher.id
                )
                self._create_partial_redemption(
                    env, voucher, order_carol, session, amount=15.0
                )

            exchange_return = self._create_return(
                env,
                order_carol,
                session,
                refund_method="exchange",
                qty_map={products["sneakers"].id: 1},
                reason="Exchange for different item",
                complete=False,
            )
            exchange = self._create_exchange(
                env,
                exchange_return,
                replacement_order,
                session,
                customer_payment=max(
                    0.0, replacement_order.amount_total - exchange_return.amount_total
                ),
            )
            self._register_xmlid(
                env, "demo_exchange_done", "cb.pos.exchange", exchange.id
            )
            self._register_xmlid(
                env, "demo_return_draft", "cb.pos.return", return_draft.id
            )

            _logger.info(
                "cb_pos_return_exchange demo data loaded successfully for %s.",
                company.display_name,
            )
        except Exception:
            _logger.exception(
                "Failed to load cb_pos_return_exchange demo data; "
                "install completed without demo transactions."
            )

    @api.model
    def _get_demo_partners(self, env):
        return {
            "alice": env.ref("cb_pos_return_exchange.demo_partner_alice"),
            "bob": env.ref("cb_pos_return_exchange.demo_partner_bob"),
            "carol": env.ref("cb_pos_return_exchange.demo_partner_carol"),
        }

    @api.model
    def _get_demo_products(self, env):
        return {
            "tee": env.ref("cb_pos_return_exchange.demo_product_tee"),
            "jeans": env.ref("cb_pos_return_exchange.demo_product_jeans"),
            "sneakers": env.ref("cb_pos_return_exchange.demo_product_sneakers"),
        }

    @api.model
    def _get_or_create_pos_config(self, env, company):
        config = env.ref("point_of_sale.pos_config_main", raise_if_not_found=False)
        if config and config.company_id == company:
            return config
        config = env["pos.config"].search([("company_id", "=", company.id)], limit=1)
        if config:
            return config

        journal = env["account.journal"].search(
            [("company_id", "=", company.id), ("type", "=", "sale")], limit=1
        )
        if not journal:
            raise ValueError("No sale journal found for demo POS configuration.")

        cash_pm = env["pos.payment.method"].search(
            [("company_id", "=", company.id), ("is_cash_count", "=", True)], limit=1
        )
        if not cash_pm:
            cash_pm = env["pos.payment.method"].create(
                {
                    "name": "Cash",
                    "is_cash_count": True,
                    "company_id": company.id,
                }
            )

        warehouse = env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1
        )
        vals = {
            "name": "Return Demo Shop",
            "company_id": company.id,
            "journal_id": journal.id,
            "payment_method_ids": [(6, 0, cash_pm.ids)],
        }
        if warehouse:
            vals["warehouse_id"] = warehouse.id
        return env["pos.config"].create(vals)

    @api.model
    def _get_or_create_session(self, env, config):
        session = config.current_session_id
        if session and session.state == "opened":
            return session
        config.open_ui()
        session = config.current_session_id
        if not session:
            raise ValueError("Could not open a POS session for demo data.")
        if session.state == "opening_control":
            session.set_opening_control(0.0, None)
        return session

    @api.model
    def _set_product_stock(self, env, products, config):
        warehouse = config.warehouse_id or env["stock.warehouse"].search(
            [("company_id", "=", config.company_id.id)], limit=1
        )
        if not warehouse:
            return
        location = warehouse.lot_stock_id
        Quant = env["stock.quant"].with_context(inventory_mode=True)
        for product in products.values():
            if not product.is_storable:
                continue
            quant = Quant.search(
                [
                    ("product_id", "=", product.id),
                    ("location_id", "=", location.id),
                ],
                limit=1,
            )
            if quant:
                quant.inventory_quantity = 100.0
                quant.action_apply_inventory()
            else:
                Quant.create(
                    {
                        "product_id": product.id,
                        "location_id": location.id,
                        "inventory_quantity": 100.0,
                    }
                ).action_apply_inventory()

    @api.model
    def _create_pos_order(self, env, session, config, partner, line_specs, pos_reference):
        order_lines = []
        for product, qty, price_unit in line_specs:
            subtotal = price_unit * qty
            order_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "qty": qty,
                        "price_unit": price_unit,
                        "price_subtotal": subtotal,
                        "price_subtotal_incl": subtotal,
                        "tax_ids": [(6, 0, [])],
                        "full_product_name": product.display_name,
                    },
                )
            )
        total = sum(line[2]["price_subtotal_incl"] for line in order_lines)
        payment_method = (
            config.payment_method_ids.filtered("is_cash_count")[:1]
            or config.payment_method_ids[:1]
        )
        if not payment_method:
            raise ValueError("POS configuration has no payment method.")

        order_uid = str(uuid.uuid4())
        order_data = {
            "name": "Order %s" % pos_reference,
            "uuid": order_uid,
            "pos_reference": pos_reference,
            "session_id": session.id,
            "partner_id": partner.id,
            "user_id": env.uid,
            "amount_total": total,
            "amount_tax": 0.0,
            "amount_paid": total,
            "amount_return": 0.0,
            "date_order": fields.Datetime.to_string(fields.Datetime.now()),
            "fiscal_position_id": False,
            "pricelist_id": config.pricelist_id.id,
            "lines": order_lines,
            "payment_ids": [
                (
                    0,
                    0,
                    {
                        "amount": total,
                        "payment_method_id": payment_method.id,
                        "name": fields.Datetime.now(),
                    },
                )
            ],
            "last_order_preparation_change": "{}",
        }
        result = env["pos.order"].sync_from_ui([order_data])
        order_ids = [item["id"] for item in result.get("pos.order", [])]
        if not order_ids:
            raise ValueError("Failed to create demo POS order %s." % pos_reference)
        order = env["pos.order"].browse(order_ids[0])
        self._register_xmlid(
            env,
            "demo_order_%s" % pos_reference.lower().replace("-", "_"),
            "pos.order",
            order.id,
        )
        return order

    @api.model
    def _create_return(
        self,
        env,
        order,
        session,
        refund_method,
        qty_map,
        reason,
        complete,
    ):
        line_commands = []
        for line in order.lines:
            qty = qty_map.get(line.product_id.id)
            if not qty:
                continue
            line_commands.append(
                (
                    0,
                    0,
                    {
                        "original_line_id": line.id,
                        "product_id": line.product_id.id,
                        "uom_id": line.product_id.uom_id.id,
                        "qty_sold": line.qty,
                        "qty": qty,
                        "price_unit": line.price_unit,
                        "discount": line.discount,
                        "tax_ids": [(6, 0, line.tax_ids.ids)],
                        "disposition": "restock",
                        "reason": reason,
                    },
                )
            )
        if not line_commands:
            raise ValueError("No return lines matched for demo return.")

        return_doc = env["cb.pos.return"].create(
            {
                "original_order_id": order.id,
                "config_id": order.config_id.id,
                "session_id": session.id,
                "partner_id": order.partner_id.id,
                "company_id": order.company_id.id,
                "currency_id": order.currency_id.id,
                "cashier_id": env.user.id,
                "refund_method": refund_method,
                "reason": reason,
                "has_receipt": True,
                "note": "Demo data — sample return transaction.",
                "line_ids": line_commands,
            }
        )
        if complete:
            return_doc.action_confirm()
            return_doc.action_done()
        return return_doc

    @api.model
    def _create_partial_redemption(self, env, voucher, order, session, amount):
        redemption_order = env["pos.order"].browse(order.id)
        voucher._redeem(amount, redemption_order, session=session)

    @api.model
    def _create_exchange(
        self, env, return_doc, replacement_order, session, customer_payment
    ):
        exchange = env["cb.pos.exchange"].create(
            {
                "return_id": return_doc.id,
                "replacement_order_id": replacement_order.id,
                "partner_id": return_doc.partner_id.id,
                "company_id": return_doc.company_id.id,
                "currency_id": return_doc.currency_id.id,
                "config_id": return_doc.config_id.id,
                "session_id": session.id,
                "cashier_id": env.user.id,
                "customer_payment": customer_payment,
                "note": "Demo data — sample exchange transaction.",
            }
        )
        exchange.action_complete()
        return exchange

    @api.model
    def _register_xmlid(self, env, name, model, res_id):
        existing = env["ir.model.data"].search(
            [("module", "=", "cb_pos_return_exchange"), ("name", "=", name)],
            limit=1,
        )
        if existing:
            existing.write({"res_id": res_id})
            return
        env["ir.model.data"].create(
            {
                "module": "cb_pos_return_exchange",
                "name": name,
                "model": model,
                "res_id": res_id,
                "noupdate": True,
            }
        )
