# -*- coding: utf-8 -*-
"""
POS-facing API for the Return & Exchange OWL frontend.

All public methods return JSON-serializable dicts with a ``success`` flag.
Heavy reads use ``search_read`` / ``read_group`` to minimize ORM overhead.
"""

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_round

_logger = logging.getLogger(__name__)

PAID_ORDER_STATES = ("paid", "done", "invoiced")
ACTIVE_RETURN_STATES = ("confirmed", "done")


class CbPosReturnApi(models.AbstractModel):
    """Backend service layer consumed by the POS OWL client."""

    _name = "cb.pos.return.api"
    _description = "POS Return API Service"

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    @api.model
    def _ok(self, **payload):
        return {"success": True, **payload}

    @api.model
    def _err(self, code, message, **extra):
        return {"success": False, "error_code": code, "error": message, **extra}

    @api.model
    def _resolve_context(self, config_id, session_id=False):
        config = self.env["pos.config"].browse(config_id).exists()
        session = (
            self.env["pos.session"].browse(session_id).exists() if session_id else False
        )
        return config, session

    @api.model
    def _require_context(self, config_id, session_id=False):
        config, session = self._resolve_context(config_id, session_id)
        if not config:
            return None, None, self._err(
                "config_missing", self.env._("POS configuration not found.")
            )
        return config, session, None

    @api.model
    def _check_company_record(self, record, config, label=None):
        """Ensure a record belongs to the POS company."""
        if not record:
            return self._err(
                "record_not_found",
                self.env._("%s not found.", label or self.env._("Record")),
            )
        company = getattr(record, "company_id", False)
        if company and company != config.company_id:
            return self._err(
                "company_mismatch",
                self.env._(
                    "%(label)s does not belong to this POS company.",
                    label=label or record._description,
                ),
            )
        return None

    @api.model
    def _resolve_lot_id(self, line, payload):
        """Resolve lot/serial from payload id or lot name."""
        lot_id = payload.get("lot_id")
        if lot_id:
            return lot_id
        lot_name = (payload.get("lot_name") or "").strip()
        if not lot_name:
            return False
        lot = self.env["stock.lot"].search(
            [
                ("name", "=", lot_name),
                ("product_id", "=", line.product_id.id),
                ("company_id", "in", [False, line.order_id.company_id.id]),
            ],
            limit=1,
        )
        return lot.id if lot else False

    @api.model
    def _log_api(self, event_type, *, success=True, config=None, session=None, **kwargs):
        self.env["cb.pos.return.audit"]._log_event(
            event_type,
            success=success,
            company=config.company_id if config else self.env.company,
            config=config,
            session=session,
            **kwargs,
        )

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------

    @api.model
    def _require_module_enabled(self, config):
        settings = self.env["cb.pos.return.config"]._get_config(
            company=config.company_id, config=config
        )
        if settings and not settings.module_enabled:
            return self._err(
                "module_disabled",
                self.env._("Return and exchange is disabled for this POS."),
            )
        return None

    @api.model
    def pos_get_settings(self, config_id, session_id=False):
        """Return policy settings for the POS return UI."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        settings = self.env["cb.pos.return.config"]._get_config(
            company=config.company_id, config=config
        )
        return self._ok(
            settings=self.env["cb.pos.return.config"]._settings_payload(settings),
            permissions={
                "create_return": self.env.user.has_group(
                    "cb_pos_return_exchange.group_cb_pos_create_return"
                ),
                "redeem_voucher": self.env.user.has_group(
                    "cb_pos_return_exchange.group_cb_pos_redeem_voucher"
                ),
                "print_voucher": self.env.user.has_group(
                    "cb_pos_return_exchange.group_cb_pos_print_voucher"
                ),
                "cancel_voucher": self.env.user.has_group(
                    "cb_pos_return_exchange.group_cb_pos_cancel_voucher"
                ),
                "cash_refund": self.env.user.has_group(
                    "cb_pos_return_exchange.group_cb_pos_cash_refund"
                ),
            },
        )

    # -------------------------------------------------------------------------
    # Find order
    # -------------------------------------------------------------------------

    @api.model
    def pos_find_order(self, config_id, session_id, search_term):
        """
        Find a paid POS order by receipt number, order name, database id,
        or linked invoice number.
        """
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        term = (search_term or "").strip()
        if not term:
            return self._err("search_required", self.env._("Search term is required."))

        orders = self._find_orders(config, term)
        if not orders:
            self._log_api(
                "validation_failure",
                success=False,
                config=config,
                session=session,
                message=self.env._("Order not found for %(term)s.", term=term),
                payload={"search_term": term, "api": "find_order"},
            )
            return self._err("order_not_found", self.env._("POS order not found."))

        orders_data = [self._serialize_order(order, config) for order in orders]
        first = orders[0]
        self._log_api(
            "order_linked",
            config=config,
            session=session,
            pos_order=first,
            message=self.env._(
                "%(count)s order(s) found for %(term)s.",
                count=len(orders),
                term=term,
            ),
            payload={"search_term": term, "order_ids": orders.ids},
        )
        # `order` kept for backward compatibility (first / best match);
        # `orders` lists every match so duplicate receipt numbers across
        # sessions can be disambiguated by the cashier.
        return self._ok(order=orders_data[0], orders=orders_data)

    @api.model
    def _find_orders(self, config, term, limit=20):
        """Resolve every paid order matching a search term.

        `pos_reference` (Receipt Number) and `name` are globally unique, so a
        match on those returns a single order. `tracking_number` (the short
        Order Number printed on receipts) resets per session and can repeat
        across sessions — every match is returned so the cashier can pick the
        right one instead of silently getting the wrong order.
        """
        Order = self.env["pos.order"]
        base_domain = [
            ("company_id", "=", config.company_id.id),
            ("state", "in", PAID_ORDER_STATES),
            ("is_refund", "=", False),
        ]
        orders = Order.browse()

        if term.isdigit():
            candidate = Order.browse(int(term)).exists()
            if (
                candidate
                and candidate.company_id == config.company_id
                and candidate.state in PAID_ORDER_STATES
                and not candidate.is_refund
            ):
                orders |= candidate

        orders |= Order.search(
            base_domain
            + [
                "|",
                "|",
                ("pos_reference", "=", term),
                ("name", "=", term),
                ("tracking_number", "=", term),
            ],
            order="date_order desc",
            limit=limit,
        )

        if not orders:
            invoice = self.env["account.move"].search(
                [
                    ("company_id", "=", config.company_id.id),
                    ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"),
                    ("name", "=", term),
                ],
                limit=1,
            )
            if invoice:
                orders |= Order.search(
                    base_domain + [("account_move", "=", invoice.id)], limit=limit
                )
        return orders

    @api.model
    def _find_order(self, config, term):
        """Resolve the single best-matching order (kept for internal callers)."""
        return self._find_orders(config, term, limit=1)[:1]

    # -------------------------------------------------------------------------
    # Find product
    # -------------------------------------------------------------------------

    @api.model
    def pos_find_product(self, config_id, session_id, barcode=None, product_id=None, partner_id=False, limit=20):
        """
        Resolve a product and list recent paid orders containing it.
        """
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        products = self._resolve_products(barcode=barcode, product_id=product_id)
        if not products:
            return self._err("product_not_found", self.env._("Product not found."))

        orders = self._find_orders_for_product(
            products, config, partner_id=partner_id, limit=limit
        )
        self._log_api(
            "return_validated",
            config=config,
            session=session,
            message=self.env._(
                "Product %(product)s (%(products)s matched) — %(count)s order(s) found.",
                product=products[0].display_name,
                products=len(products),
                count=len(orders),
            ),
            payload={
                "api": "find_product",
                "product_ids": products.ids,
                "order_count": len(orders),
            },
        )
        # `product` kept for backward compatibility (first match); `products`
        # lists every product sharing the scanned barcode.
        return self._ok(
            product=self._serialize_product(products[0]),
            products=[self._serialize_product(p) for p in products],
            orders=orders,
        )

    @api.model
    def _resolve_products(self, barcode=None, product_id=None):
        """Resolve every product matching a barcode / internal reference.

        A single barcode can be shared by several products (e.g. size or
        colour variants entered with the same code), so all matches are
        returned and their orders are aggregated. The barcode may also be
        stored on the product template rather than the sold variant, so the
        template is used as a fallback and all of its variants are returned.
        """
        Product = self.env["product.product"]
        if product_id:
            product = Product.browse(product_id).exists()
            if product:
                return product
        code = (barcode or "").strip()
        if not code:
            return Product.browse()

        # Match the barcode / internal reference in BOTH places and combine:
        #  - on the sold variant (product.product), and
        #  - on the main product (product.template), returning all its variants.
        # This covers shops that put the barcode on specific variations as
        # well as those that keep a single barcode on the main product.
        products = Product.search(
            [
                "|",
                ("barcode", "=", code),
                ("default_code", "=", code),
            ],
        )

        templates = self.env["product.template"].search(
            [
                "|",
                ("barcode", "=", code),
                ("default_code", "=", code),
            ],
        )
        if templates:
            products |= templates.product_variant_ids

        return products

    @api.model
    def _resolve_product(self, barcode=None, product_id=None):
        """Resolve the single best-matching product (kept for compatibility)."""
        return self._resolve_products(barcode=barcode, product_id=product_id)[:1]

    @api.model
    def _find_orders_for_product(self, products, config, partner_id=False, limit=20):
        line_domain = [
            ("product_id", "in", products.ids),
            ("order_id.company_id", "=", config.company_id.id),
            ("order_id.state", "in", PAID_ORDER_STATES),
            ("order_id.is_refund", "=", False),
            ("qty", ">", 0),
        ]
        if partner_id:
            line_domain.append(("order_id.partner_id", "=", partner_id))

        lines = self.env["pos.order.line"].search(
            line_domain,
            order="id desc",
            limit=limit * 5,
        )
        # Odoo 19 does not support dotted-path SQL ordering such as
        # order="order_id.date_order desc"; sort in Python instead.
        lines = lines.sorted(
            key=lambda line: line.order_id.date_order or fields.Datetime.now(),
            reverse=True,
        )
        seen = set()
        orders = []
        qty_map = self._get_returnable_qty_map(lines.ids, {l.id: l.qty for l in lines})
        for line in lines:
            oid = line.order_id.id
            if oid in seen:
                continue
            # Skip lines already fully returned/refunded so the product search
            # only surfaces orders that still have something to return.
            if qty_map.get(line.id, 0.0) <= 0:
                continue
            seen.add(oid)
            orders.append(self._serialize_order_summary(line.order_id, line, qty_map, config))
            if len(orders) >= limit:
                break
        return orders

    # -------------------------------------------------------------------------
    # Find orders by customer phone (normal return, no receipt in hand)
    # -------------------------------------------------------------------------

    @api.model
    def pos_find_orders_by_phone(self, config_id, session_id, phone, limit=20):
        """List a customer's recent paid orders, matched by phone/mobile number."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        term = (phone or "").strip()
        if len(term) < 3:
            return self._err("phone_too_short", self.env._("Enter at least 3 digits."))

        Partner = self.env["res.partner"]
        # `phone` always exists; `mobile` / `phone_mobile_search` are added by
        # optional modules, so only search them when present.
        phone_fields = [f for f in ("phone", "mobile", "phone_mobile_search") if f in Partner._fields]
        phone_domain = []
        for _i in range(len(phone_fields) - 1):
            phone_domain.append("|")
        for field_name in phone_fields:
            phone_domain.append((field_name, "ilike", term))
        partners = Partner.search(
            [("company_id", "in", [False, config.company_id.id])] + phone_domain,
            limit=50,
        )
        if not partners:
            return self._err("no_customer", self.env._("No customer found for this number."))

        orders = self.env["pos.order"].search(
            [
                ("company_id", "=", config.company_id.id),
                ("state", "in", PAID_ORDER_STATES),
                ("is_refund", "=", False),
                ("partner_id", "in", partners.ids),
            ],
            order="date_order desc",
            limit=limit,
        )
        if not orders:
            return self._err(
                "no_orders", self.env._("No orders found for this customer.")
            )
        return self._ok(orders=[self._serialize_order(order, config) for order in orders])

    # -------------------------------------------------------------------------
    # No-receipt / gift return valuation (product scan -> exchange voucher)
    # -------------------------------------------------------------------------

    @api.model
    def _lowest_price_last_30_days(self, product, config):
        """Lowest actual selling unit price for a product over the last 30 days.

        Used to value no-receipt (gift) exchanges so the shop never
        over-credits. Falls back to the current sales price when the product
        has had no recent sales.
        """
        since = fields.Datetime.now() - timedelta(days=30)
        lines = self.env["pos.order.line"].search(
            [
                ("product_id", "=", product.id),
                ("order_id.company_id", "=", config.company_id.id),
                ("order_id.state", "in", PAID_ORDER_STATES),
                ("order_id.is_refund", "=", False),
                ("order_id.date_order", ">=", since),
                ("qty", ">", 0),
            ]
        )
        prices = []
        for line in lines:
            unit = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            if unit > 0:
                prices.append(unit)
        if prices:
            return float_round(min(prices), precision_rounding=config.currency_id.rounding)
        return product.lst_price or 0.0

    @api.model
    def pos_get_product_return_value(self, config_id, session_id, barcode=None, product_id=None):
        """Resolve a scanned product and its no-receipt exchange value."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        products = self._resolve_products(barcode=barcode, product_id=product_id)
        if not products:
            return self._err("product_not_found", self.env._("Product not found."))
        product = products[0]
        unit_value = self._lowest_price_last_30_days(product, config)
        return self._ok(
            product=self._serialize_product(product),
            unit_value=unit_value,
        )

    @api.model
    def pos_create_gift_voucher(self, config_id, session_id, payload):
        """Issue a standalone exchange voucher for a no-receipt / gift return.

        The value of each scanned product is the lowest price it actually sold
        for in the last 30 days (recomputed server-side; the client value is
        never trusted). No original order is required.
        """
        if not self.env.user.has_group("cb_pos_return_exchange.group_cb_pos_create_return"):
            return self._err(
                "permission_denied",
                self.env._("You are not allowed to create returns."),
            )
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        payload = payload or {}
        lines = payload.get("lines") or []
        if not lines:
            return self._err("no_lines", self.env._("Scan at least one product."))

        total = 0.0
        detail = []
        for lp in lines:
            product = self._resolve_products(
                product_id=lp.get("product_id"), barcode=lp.get("barcode")
            )[:1]
            if not product:
                continue
            qty = max(float(lp.get("qty") or 1), 0.0)
            if qty <= 0:
                continue
            unit_value = self._lowest_price_last_30_days(product, config)
            line_total = unit_value * qty
            total += line_total
            detail.append({
                "product_id": product.id,
                "product_name": product.display_name,
                "qty": qty,
                "unit_value": unit_value,
                "amount": line_total,
            })

        total = float_round(total, precision_rounding=config.currency_id.rounding)
        if float_compare(total, 0.0, precision_rounding=config.currency_id.rounding) <= 0:
            return self._err("zero_value", self.env._("Return value is zero."))

        settings = self.env["cb.pos.return.config"]._get_config(
            company=config.company_id, config=config
        )
        Voucher = self.env["cb.pos.return.voucher"]
        try:
            with self.env.cr.savepoint():
                voucher = Voucher.create({
                    "partner_id": payload.get("partner_id") or False,
                    "company_id": config.company_id.id,
                    "currency_id": config.currency_id.id,
                    "config_id": config.id,
                    "session_id": session.id if session else False,
                    "amount": total,
                    "state": "issued",
                    "issue_date": fields.Datetime.now(),
                    "expiry_date": Voucher._compute_expiry_date(settings),
                    "note": self.env._("Gift / no-receipt exchange voucher"),
                })
        except (UserError, ValidationError, AccessError) as exc:
            return self._err("gift_voucher_failed", str(exc))

        # Bring the physically returned goods back into the POS company's stock
        # (customer location -> internal stock, restock). This is secondary to
        # issuing the voucher: a stock failure must never void the voucher, so
        # it runs in its own savepoint and only logs on error.
        picking = self.env["stock.picking"]
        try:
            with self.env.cr.savepoint():
                picking = self._create_gift_restock_picking(
                    config, session, detail, voucher
                )
        except (UserError, ValidationError, AccessError, Exception) as exc:
            _logger.warning(
                "Gift voucher %s issued but restock picking failed: %s",
                voucher.name,
                exc,
            )

        self._log_api(
            "voucher_issued",
            config=config,
            session=session,
            amount=total,
            message=self.env._(
                "Gift exchange voucher %(voucher)s issued (no receipt).",
                voucher=voucher.name,
            ),
            payload={
                "api": "create_gift_voucher",
                "lines": detail,
                "picking_id": picking.id if picking else False,
            },
        )
        return self._ok(
            voucher=self._serialize_voucher(voucher),
            amount=total,
            lines=detail,
            picking_name=picking.name if picking else False,
        )

    @api.model
    def _create_gift_restock_picking(self, config, session, detail, voucher):
        """Create and validate a restock picking for a no-receipt gift return.

        Moves each storable scanned product from the customer location back to
        the POS company's internal stock (restock disposition). Tracked
        products are skipped because no lot/serial is known without a receipt.
        Returns the created ``stock.picking`` (empty recordset if nothing to
        move or the operation type is not configured).
        """
        Picking = self.env["stock.picking"]
        picking_type = config.picking_type_id
        if not picking_type:
            return Picking

        partner = voucher.partner_id
        return_type = picking_type.return_picking_type_id or picking_type

        # Source: the customer stock location.
        location_src = (
            (partner and partner.property_stock_customer)
            or picking_type.default_location_dest_id
        )
        if not location_src or location_src.usage != "customer":
            location_src = self.env["stock.warehouse"]._get_partner_locations()[0]

        # Destination: an internal stock location to restock sellable goods.
        warehouse = config.warehouse_id or picking_type.warehouse_id
        configured_return_type = picking_type.return_picking_type_id
        location_dest = False
        if (
            configured_return_type
            and configured_return_type.default_location_dest_id
            and configured_return_type.default_location_dest_id.usage == "internal"
        ):
            location_dest = configured_return_type.default_location_dest_id
        elif picking_type.default_location_src_id:
            location_dest = picking_type.default_location_src_id
        elif warehouse:
            location_dest = warehouse.lot_stock_id
        if not location_dest:
            return Picking

        movable = []
        for item in detail:
            product = self.env["product.product"].browse(item["product_id"]).exists()
            if not product or not product.is_storable:
                continue
            if product.tracking != "none":
                # No lot/serial is known for a no-receipt return.
                continue
            qty = float(item.get("qty") or 0)
            if qty <= 0:
                continue
            movable.append((product, qty))
        if not movable:
            return Picking

        picking = Picking.create({
            "partner_id": partner.id if partner else False,
            "picking_type_id": return_type.id,
            "location_id": location_src.id,
            "location_dest_id": location_dest.id,
            "origin": self.env._("Gift exchange %(voucher)s", voucher=voucher.name),
            "company_id": config.company_id.id,
            "pos_session_id": session.id if session else False,
        })
        MoveLine = self.env["stock.move.line"]
        for product, qty in movable:
            move = self.env["stock.move"].create({
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom": product.uom_id.id,
                "picking_id": picking.id,
                "picking_type_id": return_type.id,
                "location_id": location_src.id,
                "location_dest_id": location_dest.id,
                "company_id": config.company_id.id,
                "warehouse_id": return_type.warehouse_id.id if return_type.warehouse_id else False,
                "partner_id": partner.id if partner else False,
                "description_picking": product.display_name,
            })
            MoveLine.create({
                "move_id": move.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": qty,
                "location_id": location_src.id,
                "location_dest_id": location_dest.id,
            })

        picking.action_confirm()
        settings = self.env["cb.pos.return.config"]._get_config(
            company=config.company_id, config=config
        )
        if not settings or settings.auto_validate_return_picking:
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.button_validate()
        return picking

    # -------------------------------------------------------------------------
    # Validate return
    # -------------------------------------------------------------------------

    @api.model
    def pos_validate_return(self, config_id, session_id, payload):
        """Validate a return payload without creating records."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        payload = payload or {}
        order = self.env["pos.order"].browse(payload.get("order_id")).exists()
        if not order:
            return self._err("order_not_found", self.env._("POS order not found."))
        company_error = self._check_company_record(order, config, self.env._("POS order"))
        if company_error:
            return company_error

        lines_payload = payload.get("lines") or []
        if not lines_payload:
            return self._err("no_lines", self.env._("Select at least one product to return."))

        line_ids = [lp.get("order_line_id") for lp in lines_payload if lp.get("order_line_id")]
        pos_lines = self.env["pos.order.line"].browse(line_ids).exists()
        pos_line_map = {line.id: line for line in pos_lines}
        qty_map = self._get_returnable_qty_map(
            pos_lines.ids, {pl.id: pl.qty for pl in pos_lines}
        )

        validation_lines = []
        errors = []
        amount_total = 0.0
        precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")

        for lp in lines_payload:
            line = pos_line_map.get(lp.get("order_line_id"))
            qty = float(lp.get("qty") or 0)
            lp_with_lot = dict(lp)
            if line and not lp_with_lot.get("lot_id") and lp_with_lot.get("lot_name"):
                lp_with_lot["lot_id"] = self._resolve_lot_id(line, lp_with_lot)
            vline = self._validate_return_line(
                config, order, line, qty, qty_map, precision, lp_with_lot
            )
            if vline.get("error"):
                errors.append(vline["error"])
            else:
                validation_lines.append(vline)
                amount_total += vline.get("amount_total", 0.0)

        if errors:
            self._log_api(
                "validation_failure",
                success=False,
                config=config,
                session=session,
                pos_order=order,
                message="\n".join(errors),
                payload={"api": "validate_return", "errors": errors},
            )
            return self._err("validation_failed", errors[0], errors=errors)

        refund_method = payload.get("refund_method", "voucher")
        settings = self.env["cb.pos.return.config"]._get_config(
            company=config.company_id, config=config
        )
        days_since = 0
        if order.date_order:
            days_since = max((fields.Datetime.now() - order.date_order).days, 0)

        approval_required = False
        approval_reasons = []
        if settings and settings.max_refund_days and days_since > settings.max_refund_days:
            approval_required = True
            approval_reasons.append(
                self.env._("Return is outside the maximum refund window.")
            )
        if refund_method == "cash":
            if settings and not settings.allow_cash_refund:
                return self._err(
                    "cash_refund_disabled",
                    self.env._("Cash refunds are disabled."),
                )
            if not self.env.user.has_group("cb_pos_return_exchange.group_cb_pos_cash_refund"):
                return self._err(
                    "permission_denied",
                    self.env._("You are not allowed to process cash refunds."),
                )

        result = self._ok(
            valid=True,
            approval_required=approval_required,
            approval_reasons=approval_reasons,
            days_since_sale=days_since,
            amount_total=amount_total,
            order=self._serialize_order(order, config, qty_map=qty_map),
            lines=validation_lines,
        )
        self._log_api(
            "return_validated",
            config=config,
            session=session,
            pos_order=order,
            amount=amount_total,
            message=self.env._("Return validation passed for order %(order)s.", order=order.name),
            payload={"api": "validate_return", "line_count": len(validation_lines)},
        )
        return result

    @api.model
    def _validate_return_line(self, config, order, line, qty, qty_map, precision, payload):
        if not line or line.order_id != order:
            return {"error": self.env._("Invalid order line.")}
        if line.product_id.tracking != "none" and not payload.get("lot_id"):
            return {
                "error": self.env._(
                    "Lot/serial is required for %(product)s.",
                    product=line.product_id.display_name,
                )
            }
        remaining = qty_map.get(line.id, 0.0)
        if float_compare(qty, 0.0, precision_digits=precision) <= 0:
            return {"error": self.env._("Return quantity must be positive.")}
        if float_compare(qty, remaining, precision_digits=precision) > 0:
            return {
                "error": self.env._(
                    "Return quantity exceeds remaining quantity (%(remaining)s).",
                    remaining=remaining,
                )
            }
        amounts = self._compute_line_refund_amounts(line, qty)
        return {
            "order_line_id": line.id,
            "product_id": line.product_id.id,
            "product_name": line.product_id.display_name,
            "qty": qty,
            "qty_returnable": remaining,
            "lot_id": payload.get("lot_id"),
            "disposition": payload.get("disposition", "restock"),
            "tracking": line.product_id.tracking,
            "amount_subtotal": amounts["subtotal"],
            "amount_tax": amounts["tax"],
            "amount_total": amounts["total"],
        }

    # -------------------------------------------------------------------------
    # Confirm return (create document)
    # -------------------------------------------------------------------------

    @api.model
    def pos_confirm_return(self, config_id, session_id, payload):
        """Create, confirm, and complete a return from the POS."""
        if not self.env.user.has_group("cb_pos_return_exchange.group_cb_pos_create_return"):
            return self._err(
                "permission_denied",
                self.env._("You are not allowed to create returns."),
            )

        validation = self.pos_validate_return(config_id, session_id, payload)
        if not validation.get("success") or not validation.get("valid"):
            return validation

        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        payload = payload or {}
        client_uuid = payload.get("client_uuid")
        if client_uuid:
            existing = self.env["cb.pos.return"].search(
                [("uuid", "=", client_uuid)], limit=1
            )
            if existing:
                return self._serialize_return_result(existing, duplicate=True)

        order = self.env["pos.order"].browse(payload["order_id"]).exists()
        if not order:
            return self._err("order_not_found", self.env._("POS order not found."))
        company_error = self._check_company_record(order, config, self.env._("POS order"))
        if company_error:
            return company_error

        line_commands = []
        ReturnLine = self.env["cb.pos.return.line"]
        for vline in validation["lines"]:
            pos_line = self.env["pos.order.line"].browse(vline["order_line_id"])
            prior_qty = ReturnLine._get_cumulative_returned_qty(pos_line.id)
            line_commands.append((0, 0, {
                "original_line_id": pos_line.id,
                "product_id": pos_line.product_id.id,
                "uom_id": pos_line.product_uom_id.id,
                "qty_sold": pos_line.qty,
                "qty_returned_prev": prior_qty,
                "qty": vline["qty"],
                "price_unit": pos_line.price_unit,
                "discount": pos_line.discount,
                "tax_ids": [(6, 0, pos_line.tax_ids.ids)],
                "lot_id": vline.get("lot_id") or False,
                "disposition": vline.get("disposition", "restock"),
            }))

        try:
            with self.env.cr.savepoint():
                ret = self.env["cb.pos.return"].create({
                    "original_order_id": order.id,
                    "config_id": config.id,
                    "session_id": session.id if session else False,
                    "partner_id": order.partner_id.id,
                    "company_id": config.company_id.id,
                    "cashier_id": self.env.user.id,
                    "refund_method": payload.get("refund_method", "voucher"),
                    "has_receipt": payload.get("has_receipt", True),
                    "reason": payload.get("reason") or False,
                    "note": payload.get("note") or False,
                    "uuid": client_uuid or False,
                    "line_ids": line_commands,
                })
                ret.action_confirm()
                ret.action_done()
        except (UserError, ValidationError, AccessError) as exc:
            return self._err("confirm_failed", str(exc))
        return self._serialize_return_result(ret)

    # -------------------------------------------------------------------------
    # Voucher APIs
    # -------------------------------------------------------------------------

    @api.model
    def pos_generate_voucher(self, config_id, session_id, return_id):
        """Issue or fetch the voucher for a completed return."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        ret = self.env["cb.pos.return"].browse(return_id).exists()
        if not ret:
            return self._err("return_not_found", self.env._("Return not found."))
        company_error = self._check_company_record(ret, config, self.env._("Return"))
        if company_error:
            return company_error

        if ret.state not in ("confirmed", "done"):
            return self._err(
                "invalid_state",
                self.env._("Return must be confirmed before generating a voucher."),
            )

        voucher = ret.voucher_id or ret.voucher_ids.filtered(
            lambda v: v.state in ("issued", "partial")
        )[:1]
        if not voucher:
            if ret.state != "done":
                try:
                    ret.action_done()
                except (UserError, ValidationError, AccessError) as exc:
                    return self._err("voucher_failed", str(exc))
            elif ret.refund_method in ("voucher", "store_credit"):
                voucher = self.env["cb.pos.return.voucher"]._issue_from_return(ret)
                ret.voucher_id = voucher.id
            else:
                voucher = ret.voucher_id or ret.voucher_ids[:1]

        if not voucher:
            return self._err(
                "voucher_not_applicable",
                self.env._("This return does not use voucher settlement."),
            )

        return self._ok(voucher=self._serialize_voucher(voucher))

    @api.model
    def pos_validate_voucher(self, config_id, session_id, barcode):
        """Validate a voucher barcode without redeeming it."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        voucher = self._find_voucher(config, barcode)
        if not voucher:
            return self._err("voucher_not_found", self.env._("Voucher not found."))

        voucher._expire_if_needed()
        data = self._serialize_voucher(voucher)
        data["valid"] = voucher.is_redeemable
        if not voucher.is_redeemable:
            data["validation_message"] = self.env._(
                "Voucher %(name)s is not redeemable (state: %(state)s).",
                name=voucher.name,
                state=voucher.state,
            )
        return self._ok(voucher=data)

    @api.model
    def pos_get_customer_voucher_balance(self, config_id, session_id, partner_id):
        """Return total redeemable voucher balance for a customer."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        if not partner_id:
            return self._ok(customer_balance=0.0, voucher_count=0)
        vouchers = self.env["cb.pos.return.voucher"].search(
            [
                ("partner_id", "=", partner_id),
                ("company_id", "=", config.company_id.id),
                ("state", "in", ("issued", "partial")),
            ]
        )
        balance = sum(vouchers.mapped("amount_remaining"))
        return self._ok(
            customer_balance=balance,
            voucher_count=len(vouchers),
        )

    @api.model
    def pos_validate_voucher_payment(
        self,
        config_id,
        session_id,
        barcode,
        partner_id=False,
        applied_voucher_ids=None,
    ):
        """Validate a voucher for payment screen use (no redemption)."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error

        applied_voucher_ids = applied_voucher_ids or []
        settings = self.env["cb.pos.return.config"]._get_config(
            company=config.company_id, config=config
        )
        if settings and not settings.module_enabled:
            return self._err(
                "module_disabled",
                self.env._("Return and exchange is disabled for this POS."),
            )
        if (
            settings
            and not settings.allow_multiple_voucher_usage
            and applied_voucher_ids
        ):
            return self._err(
                "multiple_vouchers_not_allowed",
                self.env._("Only one voucher can be used per order."),
            )

        voucher = self._find_voucher(config, barcode)
        if not voucher:
            return self._err("voucher_not_found", self.env._("Voucher not found."))

        voucher._expire_if_needed()
        if voucher.id in applied_voucher_ids:
            return self._err(
                "duplicate_voucher",
                self.env._("This voucher is already applied to the order."),
            )

        data = self._serialize_voucher(voucher)
        data["valid"] = voucher.is_redeemable
        if not voucher.is_redeemable:
            return self._err(
                "voucher_not_redeemable",
                self.env._(
                    "Voucher %(name)s is not redeemable (state: %(state)s).",
                    name=voucher.name,
                    state=voucher.state,
                ),
                voucher=data,
            )

        if partner_id and voucher.partner_id and voucher.partner_id.id != partner_id:
            return self._err(
                "customer_mismatch",
                self.env._("Voucher belongs to another customer."),
                voucher=data,
            )

        balance_result = self.pos_get_customer_voucher_balance(
            config_id, session_id, partner_id or voucher.partner_id.id
        )
        customer_balance = (
            balance_result.get("customer_balance", 0.0) if balance_result.get("success") else 0.0
        )
        return self._ok(
            voucher=data,
            customer_balance=customer_balance,
            voucher_amount=data.get("amount_remaining", 0.0),
        )

    @api.model
    def _coerce_pos_order_id(self, order_id):
        """Return a positive integer pos.order id or None."""
        if isinstance(order_id, dict):
            order_id = order_id.get("id")
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return None
        return order_id if order_id > 0 else None

    @api.model
    def pos_redeem_voucher(
        self, config_id, session_id, barcode, amount, order_id, issue_remainder=False
    ):
        """Redeem voucher value against a POS order."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        if not self.env.user.has_group("cb_pos_return_exchange.group_cb_pos_redeem_voucher"):
            return self._err(
                "permission_denied",
                self.env._("You are not allowed to redeem vouchers."),
            )

        order_id = self._coerce_pos_order_id(order_id)
        if not order_id:
            return self._err(
                "invalid_order_id",
                self.env._("A synced POS order is required before redeeming a voucher."),
            )

        order = self.env["pos.order"].browse(order_id).exists()
        if not order:
            return self._err("order_not_found", self.env._("POS order not found."))
        company_error = self._check_company_record(order, config, self.env._("POS order"))
        if company_error:
            return company_error

        voucher = self._find_voucher(config, barcode)
        if not voucher:
            return self._err("voucher_not_found", self.env._("Voucher not found."))

        try:
            redemption = voucher._redeem(
                float(amount),
                order,
                session=session,
                issue_remainder=issue_remainder,
            )
        except (UserError, ValidationError, AccessError) as exc:
            return self._err("redeem_failed", str(exc))

        return self._ok(
            voucher=self._serialize_voucher(voucher),
            redemption={
                "id": redemption.id,
                "amount": redemption.amount,
                "order_id": order.id,
            },
        )

    @api.model
    def _find_voucher(self, config, barcode):
        code = (barcode or "").strip()
        if not code:
            return self.env["cb.pos.return.voucher"]
        return self.env["cb.pos.return.voucher"].search(
            [
                ("barcode", "=", code),
                ("company_id", "=", config.company_id.id),
            ],
            limit=1,
        )

    # -------------------------------------------------------------------------
    # History
    # -------------------------------------------------------------------------

    @api.model
    def pos_return_history(self, config_id, session_id, order_id=None, order_line_id=None):
        """Return prior return activity for an order or specific order line."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error

        if order_line_id:
            lines = self.env["pos.order.line"].browse(order_line_id).exists()
            order = lines.order_id[:1]
        elif order_id:
            order = self.env["pos.order"].browse(order_id).exists()
            lines = order.mapped("lines")
        else:
            return self._err("missing_parameter", self.env._("order_id or order_line_id required."))

        company_error = self._check_company_record(order, config, self.env._("POS order"))
        if company_error:
            return company_error

        history = []
        for line in lines:
            history.extend(self._get_line_return_history(line))

        return self._ok(history=history)

    @api.model
    def pos_customer_returns(self, config_id, session_id, partner_id, limit=20):
        """List recent returns for a customer."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error

        if not partner_id:
            return self._err("partner_required", self.env._("Customer is required."))

        returns = self.env["cb.pos.return"].search(
            [
                ("partner_id", "=", partner_id),
                ("company_id", "=", config.company_id.id),
                ("state", "in", ACTIVE_RETURN_STATES + ("cancelled",)),
            ],
            order="create_date desc",
            limit=min(int(limit or 20), 100),
        )
        return self._ok(
            returns=[self._serialize_return_summary(r) for r in returns],
        )

    # -------------------------------------------------------------------------
    # Serialization (minimal fields for POS)
    # -------------------------------------------------------------------------

    @api.model
    def _get_returnable_qty_map(self, order_line_ids, qty_sold_map):
        """Batch-compute remaining returnable qty per POS order line."""
        if not order_line_ids:
            return {}
        precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        returned = {lid: 0.0 for lid in order_line_ids}

        groups = self.env["cb.pos.return.line"].read_group(
            [
                ("original_line_id", "in", order_line_ids),
                ("return_id.state", "in", ACTIVE_RETURN_STATES),
            ],
            ["qty:sum"],
            ["original_line_id"],
        )
        for group in groups:
            line_ref = group.get("original_line_id")
            if line_ref:
                returned[line_ref[0]] += group["qty"]

        refund_groups = self.env["pos.order.line"].read_group(
            [("refunded_orderline_id", "in", order_line_ids)],
            ["qty:sum"],
            ["refunded_orderline_id"],
        )
        for group in refund_groups:
            line_ref = group.get("refunded_orderline_id")
            if line_ref:
                returned[line_ref[0]] += abs(group["qty"])

        result = {}
        for lid in order_line_ids:
            sold = abs(qty_sold_map.get(lid, 0.0))
            remaining = float_round(sold - returned.get(lid, 0.0), precision_digits=precision)
            result[lid] = remaining if float_compare(remaining, 0.0, precision_digits=precision) > 0 else 0.0
        return result

    @api.model
    def _serialize_order(self, order, config, qty_map=None):
        lines = order.lines.filtered(lambda l: l.qty > 0)
        if qty_map is None:
            qty_map = self._get_returnable_qty_map(lines.ids, {l.id: l.qty for l in lines})
        return {
            "id": order.id,
            "name": order.name,
            "pos_reference": order.pos_reference,
            "partner_id": order.partner_id.id,
            "partner_name": order.partner_id.display_name,
            "amount_total": order.amount_total,
            "date_order": fields.Datetime.to_string(order.date_order),
            "invoice_id": order.account_move.id if order.account_move else False,
            "invoice_name": order.account_move.name if order.account_move else False,
            "fiscal_position_id": order.fiscal_position_id.id if order.fiscal_position_id else False,
            "warehouse_id": (
                config.warehouse_id.id
                if config.warehouse_id
                else config.picking_type_id.warehouse_id.id
                if config.picking_type_id
                else False
            ),
            # Include every sold line; those already fully returned carry
            # qty_returnable = 0 and are shown disabled on the return screen.
            "lines": [
                self._serialize_order_line(line, qty_map)
                for line in lines
            ],
        }

    @api.model
    def _serialize_order_summary(self, order, highlight_line, qty_map, config):
        data = self._serialize_order(order, config, qty_map=qty_map)
        data["highlight_line_id"] = highlight_line.id
        return data

    @api.model
    def _serialize_order_line(self, line, qty_map):
        return {
            "id": line.id,
            "product_id": line.product_id.id,
            "product_name": line.product_id.display_name,
            "qty": line.qty,
            "qty_returnable": qty_map.get(line.id, 0.0),
            "price_unit": line.price_unit,
            "discount": line.discount,
            "tracking": line.product_id.tracking,
            "is_storable": line.product_id.is_storable,
            "tax_ids": line.tax_ids.ids,
            "attribute_value_ids": line.attribute_value_ids.ids,
            "lot_names": line.pack_lot_ids.mapped("lot_name"),
        }

    @api.model
    def _serialize_product(self, product):
        return {
            "id": product.id,
            "name": product.display_name,
            "barcode": product.barcode or "",
            "default_code": product.default_code or "",
            "tracking": product.tracking,
            "is_storable": product.is_storable,
            "uom_id": product.uom_id.id,
        }

    @api.model
    def _serialize_voucher(self, voucher):
        return {
            "id": voucher.id,
            "name": voucher.name,
            "barcode": voucher.barcode,
            "state": voucher.state,
            "amount": voucher.amount,
            "amount_redeemed": voucher.amount_redeemed,
            "amount_remaining": voucher.amount_remaining,
            "is_redeemable": voucher.is_redeemable,
            "expiry_date": fields.Datetime.to_string(voucher.expiry_date)
            if voucher.expiry_date
            else False,
            "partner_id": voucher.partner_id.id,
            "partner_name": voucher.partner_id.display_name,
            "return_id": voucher.return_id.id if voucher.return_id else False,
        }

    @api.model
    def _serialize_return_summary(self, ret):
        return {
            "id": ret.id,
            "name": ret.name,
            "state": ret.state,
            "date": fields.Datetime.to_string(ret.create_date),
            "amount_total": ret.amount_total,
            "refund_method": ret.refund_method,
            "voucher_id": (ret.voucher_id or ret.voucher_ids[:1]).id
            if (ret.voucher_id or ret.voucher_ids)
            else False,
            "credit_note_id": ret.account_move_id.id if ret.account_move_id else False,
            "original_order_id": ret.original_order_id.id,
            "original_order_name": ret.original_order_id.pos_reference or ret.original_order_id.name,
        }

    @api.model
    def _serialize_return_result(self, ret, duplicate=False):
        return self._ok(
            duplicate=duplicate,
            return_id=ret.id,
            return_name=ret.name,
            state=ret.state,
            amount_total=ret.amount_total,
            voucher=self._serialize_voucher(
                ret.voucher_id or ret.voucher_ids[:1]
            )
            if (ret.voucher_id or ret.voucher_ids)
            else False,
            credit_note_id=ret.account_move_id.id if ret.account_move_id else False,
        )

    @api.model
    def _get_line_return_history(self, line):
        rows = self.env["cb.pos.return.line"].search_read(
            [
                ("original_line_id", "=", line.id),
                ("return_id.state", "in", ACTIVE_RETURN_STATES),
            ],
            ["qty", "return_id", "price_subtotal", "price_tax"],
            order="create_date desc",
            limit=50,
        )
        if not rows:
            return []

        return_ids = list({r["return_id"][0] for r in rows if r.get("return_id")})
        returns = {
            r["id"]: r
            for r in self.env["cb.pos.return"].search_read(
                [("id", "in", return_ids)],
                ["name", "state", "refund_method", "create_date", "voucher_id", "amount_total"],
            )
        }
        history = []
        for row in rows:
            ret_ref = row.get("return_id")
            if not ret_ref:
                continue
            ret = returns.get(ret_ref[0], {})
            history.append({
                "return_id": ret_ref[0],
                "return_name": ret.get("name"),
                "state": ret.get("state"),
                "refund_method": ret.get("refund_method"),
                "date": fields.Datetime.to_string(ret.get("create_date")),
                "qty": row["qty"],
                "amount": (row.get("price_subtotal") or 0.0) + (row.get("price_tax") or 0.0),
                "order_line_id": line.id,
                "product_id": line.product_id.id,
                "product_name": line.product_id.display_name,
                "voucher_id": ret.get("voucher_id") and ret["voucher_id"][0],
            })
        return history

    @api.model
    def _compute_line_refund_amounts(self, line, qty):
        price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
        subtotal = price * qty
        tax = 0.0
        total = subtotal
        if line.tax_ids:
            fpos = line.order_id.fiscal_position_id
            taxes = (fpos.map_tax(line.tax_ids) if fpos else line.tax_ids).compute_all(
                price,
                currency=line.currency_id,
                quantity=qty,
                product=line.product_id,
                partner=line.order_id.partner_id,
            )
            subtotal = taxes.get("total_excluded", subtotal)
            total = taxes.get("total_included", subtotal)
            tax = total - subtotal
        return {"subtotal": subtotal, "tax": tax, "total": total}

    # -------------------------------------------------------------------------
    # Barcode classification
    # -------------------------------------------------------------------------

    @api.model
    def _barcode_candidates(self, barcode):
        """Build normalized lookup keys for EAN-13, UPC-A, and Code128 scans."""
        raw = (barcode or "").strip()
        if not raw:
            return []
        candidates = []
        seen = set()

        def add(value):
            value = (value or "").strip()
            if value and value not in seen:
                seen.add(value)
                candidates.append(value)

        add(raw)
        add(raw.upper())

        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            add(digits)
            if len(digits) == 12:
                add(f"0{digits}")
            if len(digits) == 13 and digits.startswith("0"):
                add(digits[1:])
            if len(digits) < 13:
                add(digits.lstrip("0") or digits)

        alnum = "".join(ch for ch in raw if ch.isalnum())
        if alnum and alnum != raw:
            add(alnum)
            add(alnum.upper())

        return candidates

    @api.model
    def _detect_barcode_format(self, barcode):
        raw = (barcode or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) == 13:
            return "ean13"
        if len(digits) == 12:
            return "upc_a"
        if len(digits) == 8:
            return "ean8"
        if raw.isdigit():
            return "numeric"
        return "code128"

    @api.model
    def pos_classify_barcode(self, config_id, session_id, barcode):
        """Classify a scanned barcode as product, voucher, return, or order."""
        config, session, error = self._require_context(config_id, session_id)
        if error:
            return error
        disabled = self._require_module_enabled(config)
        if disabled:
            return disabled

        raw = (barcode or "").strip()
        if not raw:
            return self._err("barcode_empty", self.env._("Barcode is empty."))

        settings = self.env["cb.pos.return.config"]._get_config(
            company=config.company_id, config=config
        )
        if settings and not settings.auto_barcode_detect:
            return self._err(
                "barcode_disabled",
                self.env._("Automatic barcode detection is disabled."),
            )

        candidates = self._barcode_candidates(raw)
        barcode_format = self._detect_barcode_format(raw)
        voucher_prefix = (settings.voucher_barcode_prefix if settings else "VCH/") or "VCH/"
        return_prefix = (settings.return_barcode_prefix if settings else "RET/") or "RET/"

        # Prefix heuristics (Code128 document barcodes)
        upper = raw.upper()
        if upper.startswith(voucher_prefix.upper()):
            voucher = self._find_voucher(config, raw)
            if voucher:
                return self._barcode_classified(
                    "voucher", barcode_format, raw, voucher=voucher, config=config, session=session
                )
        if upper.startswith(return_prefix.upper()):
            ret = self.env["cb.pos.return"].search(
                [
                    ("name", "in", candidates),
                    ("company_id", "=", config.company_id.id),
                ],
                limit=1,
            )
            if ret:
                return self._barcode_classified(
                    "return", barcode_format, raw, return_doc=ret, config=config, session=session
                )

        voucher = self.env["cb.pos.return.voucher"].search(
            [
                ("barcode", "in", candidates),
                ("company_id", "=", config.company_id.id),
            ],
            limit=1,
        )
        if voucher:
            return self._barcode_classified(
                "voucher", barcode_format, raw, voucher=voucher, config=config, session=session
            )

        ret = self.env["cb.pos.return"].search(
            [
                ("name", "in", candidates),
                ("company_id", "=", config.company_id.id),
            ],
            limit=1,
        )
        if ret:
            return self._barcode_classified(
                "return", barcode_format, raw, return_doc=ret, config=config, session=session
            )

        products = self.env["product.product"].browse()
        for candidate in candidates:
            products |= self._resolve_products(barcode=candidate)
        if products:
            return self._barcode_classified(
                "product",
                barcode_format,
                raw,
                product=products[0],
                config=config,
                session=session,
            )

        for candidate in candidates:
            order = self._find_order(config, candidate)
            if order:
                return self._barcode_classified(
                    "order",
                    barcode_format,
                    raw,
                    order=order,
                    config=config,
                    session=session,
                )

        self._log_api(
            "validation_failure",
            success=False,
            config=config,
            session=session,
            message=self.env._("Unknown barcode %(barcode)s.", barcode=raw),
            payload={"api": "classify_barcode", "barcode": raw, "format": barcode_format},
        )
        return self._err(
            "barcode_unknown",
            self.env._("No product, voucher, or return matches this barcode."),
            barcode=raw,
            format=barcode_format,
        )

    @api.model
    def _barcode_classified(
        self,
        barcode_type,
        barcode_format,
        raw,
        *,
        config,
        session,
        voucher=None,
        return_doc=None,
        product=None,
        order=None,
    ):
        actions = []
        label = raw
        if barcode_type == "voucher" and voucher:
            label = voucher.barcode or voucher.name
            actions = [
                {"id": "redeem_voucher", "label": self.env._("Redeem Voucher")},
                {"id": "view_voucher", "label": self.env._("View Voucher")},
            ]
            data = self._serialize_voucher(voucher)
        elif barcode_type == "return" and return_doc:
            label = return_doc.name
            actions = [
                {"id": "view_return", "label": self.env._("View Return")},
                {"id": "return_history", "label": self.env._("Return History")},
            ]
            data = self._serialize_return_summary(return_doc)
        elif barcode_type == "product" and product:
            label = product.display_name
            actions = [
                {"id": "return_product", "label": self.env._("Return Product")},
                {"id": "find_orders", "label": self.env._("Find Orders")},
            ]
            data = self._serialize_product(product)
        elif barcode_type == "order" and order:
            label = order.pos_reference or order.name
            actions = [
                {"id": "start_return", "label": self.env._("Start Return")},
                {"id": "return_history", "label": self.env._("Return History")},
            ]
            data = self._serialize_order(order, config)
        else:
            return self._err("barcode_unknown", self.env._("Barcode could not be classified."))

        self._log_api(
            "return_validated",
            config=config,
            session=session,
            message=self.env._(
                "Barcode classified as %(type)s: %(label)s.",
                type=barcode_type,
                label=label,
            ),
            payload={
                "api": "classify_barcode",
                "barcode": raw,
                "format": barcode_format,
                "type": barcode_type,
            },
        )
        return self._ok(
            barcode_type=barcode_type,
            barcode_format=barcode_format,
            barcode=raw,
            label=label,
            actions=actions,
            data=data,
        )

    # -------------------------------------------------------------------------
    # Backward-compatible aliases for earlier RPC names
    # -------------------------------------------------------------------------

    @api.model
    def pos_lookup_order(self, order_ref, config_id):
        return self.pos_find_order(config_id, False, order_ref)

    @api.model
    def pos_lookup_voucher(self, barcode, config_id):
        return self.pos_validate_voucher(config_id, False, barcode)
