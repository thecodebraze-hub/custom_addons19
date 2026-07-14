# Configuration Guide

Return and exchange behaviour is controlled by **`cb.pos.return.config`** records. Settings resolve in this order:

1. **POS-specific** record (`config_id` = your POS Configuration)
2. **Company-wide** record (`config_id` empty, `company_id` set)

![Company-wide settings](images/placeholder-company-settings.png)

**Menu:** Point of Sale → Configuration → Return & Exchange Settings

![Per-POS settings](images/placeholder-pos-config-settings.png)

**Menu:** Point of Sale → Configuration → Point of Sale → open a shop → **Returns & Exchanges** tab

---

## General

| Setting | Field | Default | Description |
|---------|-------|---------|-------------|
| Enable Module | `module_enabled` | `True` | Master switch — disables all POS return/exchange/voucher features when off |
| Maximum Refund Days | `max_refund_days` | `30` | Days after sale; exceeding triggers **approval required** flag in validation |
| Require Original Receipt | `require_receipt` | `False` | Block confirmation if customer did not present receipt |
| Require Original Invoice | `require_original_invoice` | `False` | Reject returns when POS order has no posted invoice |
| Enable Audit Log | `enable_audit_log` | `True` | Write events to `cb.pos.return.audit` |

### Example — strict retail policy

```
module_enabled          = True
max_refund_days         = 14
require_receipt         = True
require_original_invoice = False
allow_cash_refund       = False
```

---

## Refunds & Vouchers

| Setting | Field | Default | Description |
|---------|-------|---------|-------------|
| Allow Cash Refund | `allow_cash_refund` | `True` | When off, cash refund method is rejected at validation |
| Voucher Expiry Days | `voucher_validity_days` | `365` | Days until issued vouchers expire (cron checks daily) |
| Allow Partial Voucher | `allow_partial_voucher_redemption` | `True` | Redeem part of voucher balance on an order |
| Allow Multiple Vouchers | `allow_multiple_voucher_usage` | `True` | Apply more than one voucher on same POS order |
| Auto-Print Voucher | `auto_print_voucher` | `False` | Print voucher receipt immediately after issue |
| Issue Remainder Voucher | `issue_remainder_voucher` | `False` | On partial redemption, issue new voucher for unused balance |

### Example — gift-card style vouchers

```
voucher_validity_days              = 730
allow_partial_voucher_redemption   = True
allow_multiple_voucher_usage       = False
auto_print_voucher                 = True
issue_remainder_voucher            = True
```

---

## Inventory

| Setting | Field | Default | Description |
|---------|-------|---------|-------------|
| Quarantine Location | `quarantine_location_id` | — | Internal location for **quarantine** disposition lines |
| Validate Lot/Serial | `validate_lot_from_sale` | `True` | Require lot/serial from original delivery on tracked products |
| Auto-Validate Pickings | `auto_validate_return_picking` | `True` | Validate stock pickings when return is confirmed |

**Disposition options per return line:** `restock`, `quarantine`, `scrap`

---

## Accounting

| Setting | Field | Default | Description |
|---------|-------|---------|-------------|
| Auto-Create Credit Notes | `auto_create_credit_note` | `True` | Create credit note when return completes against invoiced order |
| Auto-Post Credit Notes | `auto_post_credit_note` | `True` | Post credit note after creation |

> Credit note creation requires the original POS order to have a posted `account.move`. Non-invoiced POS orders skip accounting integration.

---

## Barcode

| Setting | Field | Default | Description |
|---------|-------|---------|-------------|
| Voucher Barcode Prefix | `voucher_barcode_prefix` | `VCH/` | Prefix for voucher document scans (Code128) |
| Return Barcode Prefix | `return_barcode_prefix` | `RET/` | Prefix for return document scans |
| Auto-Detect Barcodes | `auto_barcode_detect` | `True` | Classify scans as product / voucher / return / order |
| Barcode Type | `voucher_barcode_type` | `code128` | Linear barcode on printed vouchers: Code128, EAN-13, EAN-8 |
| QR Code | `voucher_use_qr_code` | `False` | Add QR code on voucher receipts |

### Scanner setup

- USB and wireless scanners work as keyboard wedges — no extra driver needed.
- Ensure product barcodes do not collide with `VCH/` or `RET/` prefixes.

---

## Receipts

| Setting | Field | Default | Description |
|---------|-------|---------|-------------|
| Default Receipt Width | `receipt_paper_width` | `80` | `58` or `80` mm thermal templates |
| Header Message | `receipt_header_message` | — | Optional text below logo |
| Thank You Message | `receipt_thank_you_message` | Thank you… | Footer message (translatable) |

Reports:

- `action_report_cb_return_receipt_{58,80}`
- `action_report_cb_voucher_receipt_{58,80}`
- `action_report_cb_exchange_receipt_{58,80}`

![Return receipt example](images/placeholder-return-receipt-80mm.png)

---

## Security groups

Configured under **Settings → Users** → **POS Return & Exchange** privilege.

| Group | Technical ID | Grants |
|-------|--------------|--------|
| Create Return | `group_cb_pos_create_return` | Create and confirm returns |
| Redeem Voucher | `group_cb_pos_redeem_voucher` | Redeem vouchers at payment |
| Print Voucher | `group_cb_pos_print_voucher` | Print voucher receipts |
| Cancel Voucher | `group_cb_pos_cancel_voucher` | Cancel issued/partial vouchers |
| Cash Refund | `group_cb_pos_cash_refund` | Cash refund settlement |
| View Reports | `group_cb_pos_view_reports` | Analytics menus |
| Modify Settings | `group_cb_pos_modify_settings` | Edit configuration records |

**Role inheritance:** Cashier ⊂ Manager ⊂ Administrator

---

## Multi-company

- Settings and documents are company-scoped (`_check_company_auto`).
- Record rules restrict returns, vouchers, and exchanges to the user's allowed companies.
- Each company should have one company-wide `cb.pos.return.config` (created on install).

---

## Configuration API payload (POS)

When the POS loads, `pos_get_settings` returns a subset of these fields to the client. See [API Documentation](API.md#pos_get_settings).
