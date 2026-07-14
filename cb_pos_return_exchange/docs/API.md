# API Documentation

POS-facing RPC reference for **CodeBraze POS Return & Exchange**.

---

## Overview

| Service | Model | Transport |
|---------|-------|-----------|
| Return / Voucher / Barcode API | `cb.pos.return.api` | `AbstractModel` — `@api.model` methods |
| Exchange API | `cb.pos.exchange` | `pos_create_exchange` on exchange model |

All `cb.pos.return.api` methods return JSON-serializable **dicts** with a `success` boolean.

### Response envelope

**Success:**

```json
{
  "success": true,
  "...": "method-specific fields"
}
```

**Error:**

```json
{
  "success": false,
  "error_code": "order_not_found",
  "error": "POS order not found."
}
```

### Calling from POS JavaScript

```javascript
await this.pos.data.call("cb.pos.return.api", "pos_find_order", [
    configId,
    sessionId,
    "Order 00001-001-0001",
]);
```

Wrapper: `PosReturnApiService` in `static/src/app/services/pos_return_api_service.js`.

### Calling from Python (tests / server)

```python
result = self.env["cb.pos.return.api"].pos_confirm_return(
    config.id,
    session.id,
    payload,
)
self.assertTrue(result["success"])
```

---

## Common parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `config_id` | `int` | `pos.config` ID for current shop |
| `session_id` | `int` | `pos.session` ID (optional for some read-only calls) |

---

## Error codes

| Code | Meaning |
|------|---------|
| `config_missing` | Invalid `config_id` |
| `module_disabled` | `module_enabled = False` on resolved settings |
| `permission_denied` | User lacks required security group |
| `order_not_found` | Order does not exist or not searchable |
| `search_required` | Empty search term |
| `no_lines` | Return payload has no lines |
| `validation_failed` | Business rule failed (see `errors` array) |
| `cash_refund_disabled` | Cash refund not allowed |
| `confirm_failed` | Exception during return confirm |
| `return_not_found` | Return ID invalid |
| `voucher_not_found` | Barcode not matched |
| `voucher_not_redeemable` | Expired, cancelled, or fully redeemed |
| `duplicate_voucher` | Same voucher already on order |
| `multiple_vouchers_not_allowed` | Settings block multi-voucher |
| `customer_mismatch` | Voucher partner ≠ order partner |
| `redeem_failed` | Redemption exception message |
| `barcode_empty` | Empty scan |
| `barcode_disabled` | `auto_barcode_detect = False` |
| `barcode_unknown` | No match for classification |
| `missing_parameter` | Required argument missing |
| `partner_required` | Customer ID required |
| `offline` | Client-side only — no network |

---

## Settings

### `pos_get_settings`

Load policies and user permissions for the POS UI.

**Signature:** `pos_get_settings(config_id, session_id=False)`

**Example request (JS):**

```javascript
const res = await returnApi.getSettings();
```

**Example response:**

```json
{
  "success": true,
  "settings": {
    "module_enabled": true,
    "max_refund_days": 30,
    "voucher_validity_days": 365,
    "voucher_expiry_days": 365,
    "require_receipt": false,
    "allow_cash_refund": true,
    "allow_partial_voucher_redemption": true,
    "allow_partial_voucher": true,
    "allow_multiple_voucher_usage": true,
    "auto_print_voucher": false,
    "require_original_invoice": false,
    "auto_create_credit_note": true,
    "validate_lot_from_sale": true,
    "voucher_barcode_prefix": "VCH/",
    "voucher_barcode_type": "code128",
    "voucher_use_qr_code": false,
    "return_barcode_prefix": "RET/",
    "auto_barcode_detect": true
  },
  "permissions": {
    "create_return": true,
    "redeem_voucher": true,
    "print_voucher": true,
    "cancel_voucher": false,
    "cash_refund": false
  }
}
```

---

## Orders & products

### `pos_find_order`

Find a paid, non-refund POS order.

**Signature:** `pos_find_order(config_id, session_id, search_term)`

**Search matches:** database ID, `pos_reference`, order `name`, posted invoice `name`.

**Example:**

```python
api.pos_find_order(config.id, session.id, "Shop/0012-003-0045")
```

**Success response (abbreviated):**

```json
{
  "success": true,
  "order": {
    "id": 42,
    "name": "Shop/0012-003-0045",
    "pos_reference": "Order 0012-003-0045",
    "partner_id": 7,
    "partner_name": "Alice Customer",
    "amount_total": 150.0,
    "date_order": "2026-07-01 14:30:00",
    "invoice_id": false,
    "lines": [
      {
        "id": 101,
        "product_id": 25,
        "product_name": "Blue T-Shirt",
        "qty": 2.0,
        "qty_returnable": 2.0,
        "price_unit": 50.0,
        "tracking": "none",
        "is_storable": true
      }
    ]
  }
}
```

### `pos_find_product`

Resolve product by barcode or ID; return recent orders containing it.

**Signature:** `pos_find_product(config_id, session_id, barcode=None, product_id=None, partner_id=False, limit=20)`

**Example:**

```javascript
await returnApi.findProduct({ barcode: "5901234123457", limit: 10 });
```

---

## Returns

### `pos_validate_return`

Validate without creating records.

**Signature:** `pos_validate_return(config_id, session_id, payload)`

**Payload schema:**

```json
{
  "order_id": 42,
  "refund_method": "voucher",
  "has_receipt": true,
  "reason": "Wrong size",
  "note": "Customer wants store credit",
  "lines": [
    {
      "order_line_id": 101,
      "qty": 1.0,
      "disposition": "restock",
      "lot_id": false
    }
  ]
}
```

| Field | Values |
|-------|--------|
| `refund_method` | `cash`, `card`, `original_payment`, `voucher`, `store_credit`, `exchange`, `mixed` |
| `disposition` | `restock`, `quarantine`, `scrap` |

**Success response:**

```json
{
  "success": true,
  "valid": true,
  "approval_required": false,
  "approval_reasons": [],
  "days_since_sale": 5,
  "amount_total": 50.0,
  "order": { "...": "..." },
  "lines": [ { "order_line_id": 101, "qty": 1.0, "amount_total": 50.0 } ]
}
```

### `pos_confirm_return`

Validate, create `cb.pos.return`, confirm, and complete.

**Signature:** `pos_confirm_return(config_id, session_id, payload)`

**Additional payload fields:**

| Field | Description |
|-------|-------------|
| `client_uuid` | Idempotency key — duplicate calls return same return with `"duplicate": true` |

**Example (Python):**

```python
payload = {
    "order_id": order.id,
    "refund_method": "voucher",
    "has_receipt": True,
    "reason": "Defective",
    "client_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "lines": [{"order_line_id": line.id, "qty": 1, "disposition": "restock"}],
}
result = api.pos_confirm_return(config.id, session.id, payload)
```

**Success response:**

```json
{
  "success": true,
  "duplicate": false,
  "return_id": 15,
  "return_name": "RET/2026/00015",
  "state": "done",
  "amount_total": 50.0,
  "voucher": {
    "id": 8,
    "name": "VCH/2026/00008",
    "barcode": "VCH/RV/2026/00008",
    "state": "issued",
    "amount": 50.0,
    "amount_remaining": 50.0,
    "is_redeemable": true
  },
  "credit_note_id": false
}
```

**Required group:** `group_cb_pos_create_return`

---

## Vouchers

### `pos_generate_voucher`

Issue or fetch voucher for a completed return.

**Signature:** `pos_generate_voucher(config_id, session_id, return_id)`

### `pos_validate_voucher`

Check voucher barcode without redeeming.

**Signature:** `pos_validate_voucher(config_id, session_id, barcode)`

### `pos_get_customer_voucher_balance`

**Signature:** `pos_get_customer_voucher_balance(config_id, session_id, partner_id)`

**Response:**

```json
{
  "success": true,
  "customer_balance": 125.0,
  "voucher_count": 3
}
```

### `pos_validate_voucher_payment`

Pre-validate for payment screen (duplicate + multi-voucher checks).

**Signature:** `pos_validate_voucher_payment(config_id, session_id, barcode, partner_id=False, applied_voucher_ids=None)`

**Example:**

```javascript
await returnApi.validateVoucherPayment("VCH/RV/2026/00008", {
    partnerId: order.partner_id,
    appliedVoucherIds: [7],
});
```

### `pos_redeem_voucher`

Redeem amount against a POS order.

**Signature:** `pos_redeem_voucher(config_id, session_id, barcode, amount, order_id, issue_remainder=False)`

**Example:**

```python
api.pos_redeem_voucher(
    config.id, session.id,
    "VCH/RV/2026/00008",
    25.0,
    order.id,
    issue_remainder=True,
)
```

**Success response:**

```json
{
  "success": true,
  "voucher": { "id": 8, "amount_remaining": 25.0, "state": "partial" },
  "redemption": { "id": 22, "amount": 25.0, "order_id": 99 }
}
```

**Required group:** `group_cb_pos_redeem_voucher`

---

## History

### `pos_return_history`

**Signature:** `pos_return_history(config_id, session_id, order_id=None, order_line_id=None)`

### `pos_customer_returns`

**Signature:** `pos_customer_returns(config_id, session_id, partner_id, limit=20)`

---

## Barcode

### `pos_classify_barcode`

Classify scan as `product`, `voucher`, `return`, or `order`.

**Signature:** `pos_classify_barcode(config_id, session_id, barcode)`

**Success response (product example):**

```json
{
  "success": true,
  "barcode_type": "product",
  "format": "ean13",
  "barcode": "5901234123457",
  "product": {
    "id": 25,
    "name": "Blue T-Shirt",
    "barcode": "5901234123457",
    "tracking": "none",
    "is_storable": true
  }
}
```

**Success response (voucher example):**

```json
{
  "success": true,
  "barcode_type": "voucher",
  "format": "code128",
  "barcode": "VCH/RV/2026/00008",
  "voucher": {
    "id": 8,
    "barcode": "VCH/RV/2026/00008",
    "amount_remaining": 50.0,
    "is_redeemable": true
  }
}
```

---

## Exchange API

Model: **`cb.pos.exchange`**  
Method: **`pos_create_exchange`**

**Signature:** `pos_create_exchange(payload, config_id, session_id)`

> Note: argument order differs from `cb.pos.return.api` methods.

**Payload:**

```json
{
  "return_id": 15,
  "replacement_order_id": 100,
  "customer_payment": 10.0,
  "voucher_used": false,
  "auto_complete": true
}
```

**Example (JS):**

```javascript
await returnApi.createExchange({
    return_id: returnId,
    replacement_order_id: newOrder.id,
    customer_payment: 0,
    voucher_used: false,
    auto_complete: true,
});
```

**Response:**

```json
{
  "id": 3,
  "name": "EXC/2026/00003",
  "state": "done",
  "difference_amount": -10.0,
  "settlement_mode": "voucher",
  "voucher_id": 9
}
```

---

## Legacy aliases

| Alias | Redirects to |
|-------|--------------|
| `pos_lookup_order(order_ref, config_id)` | `pos_find_order(config_id, False, order_ref)` |
| `pos_lookup_voucher(barcode, config_id)` | `pos_validate_voucher(config_id, False, barcode)` |

---

## Voucher object schema

Returned by `_serialize_voucher`:

```json
{
  "id": 8,
  "name": "VCH/2026/00008",
  "barcode": "VCH/RV/2026/00008",
  "state": "issued",
  "amount": 50.0,
  "amount_redeemed": 0.0,
  "amount_remaining": 50.0,
  "is_redeemable": true,
  "expiry_date": "2027-07-01 00:00:00",
  "partner_id": 7,
  "partner_name": "Alice Customer",
  "return_id": 15
}
```

**States:** `issued`, `partial`, `redeemed`, `expired`, `cancelled`

---

## Return summary schema

```json
{
  "id": 15,
  "name": "RET/2026/00015",
  "state": "done",
  "date": "2026-07-09 10:15:00",
  "amount_total": 50.0,
  "refund_method": "voucher",
  "voucher_id": 8,
  "credit_note_id": false,
  "original_order_id": 42,
  "original_order_name": "Order 0012-003-0045"
}
```

---

## Audit events

When `enable_audit_log` is true, API calls log to `cb.pos.return.audit` with event types including:

- `return_validated`
- `validation_failure`
- `order_linked`
- `voucher_printed`
- `voucher_cancelled`

---

## Full integration example

End-to-end return + partial voucher redemption:

```python
# 1. Validate
validation = env["cb.pos.return.api"].pos_validate_return(
    config.id, session.id,
    {"order_id": order.id, "lines": [{"order_line_id": line.id, "qty": 1}]},
)
assert validation["success"] and validation["valid"]

# 2. Confirm
confirm = env["cb.pos.return.api"].pos_confirm_return(
    config.id, session.id,
    {
        "order_id": order.id,
        "refund_method": "voucher",
        "client_uuid": "test-uuid-001",
        "lines": [{"order_line_id": line.id, "qty": 1, "disposition": "restock"}],
    },
)
voucher_barcode = confirm["voucher"]["barcode"]

# 3. New sale — redeem half
new_order = ...  # pos.order from sync_from_ui
redeem = env["cb.pos.return.api"].pos_redeem_voucher(
    config.id, session.id,
    voucher_barcode,
    confirm["amount_total"] / 2,
    new_order.id,
)
assert redeem["success"]
```

---

## Related

- [Developer Guide](DEVELOPER_GUIDE.md) — architecture and extension points
- [Configuration Guide](CONFIGURATION.md) — settings that affect API behaviour
- [User Manual](USER_MANUAL.md) — cashier-facing workflows
