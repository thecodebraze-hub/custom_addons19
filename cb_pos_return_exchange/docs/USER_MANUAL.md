# User Manual

This guide covers day-to-day POS operations for cashiers and store managers using **CodeBraze POS Return & Exchange**.

---

## Getting started in POS

1. Log in to the POS session with a user assigned **POS Return & Exchange → Cashier** (minimum).
2. On the **Product** screen, use the control buttons:
   - **Return** — process a product return
   - **Exchange** — return items and sell replacements in one flow

![POS product screen](images/placeholder-pos-product-screen.png)

If buttons are missing, ask a manager to enable **Module** in Return & Exchange settings.

---

## Processing a return

### 1. Open the Return screen

Tap **Return**. The return screen lets you find the original sale and select lines to return.

![Return screen](images/placeholder-pos-return-screen.png)

### 2. Find the original order

Search by any of:

- Receipt / POS reference (e.g. `Order 00012-001-0001`)
- Order name
- Customer name or phone
- Product barcode (finds orders containing that product)

**Example:** Customer presents receipt `Shop/0005`. Type `0005` in the search box and select the matching order.

### 3. Select lines and quantities

- Tap each line to return.
- Adjust quantity (partial returns supported).
- For **tracked products** (lot/serial), select the correct lot.
- Choose **disposition**:
  - **Restock** — return to sellable stock
  - **Quarantine** — send to quarantine location (if configured)
  - **Scrap** — write off stock

### 4. Choose refund method

| Method | When to use |
|--------|-------------|
| **Voucher** | Default — customer receives store credit voucher |
| **Cash** | Manager permission required; must be enabled in settings |
| **Original Payment** | Reverse to original card/cash method where supported |
| **Store Credit** | Account-based store credit (voucher variant) |

### 5. Confirm

- Enter return **reason** (recommended).
- Toggle **Has receipt** if the customer presented the original receipt (required when setting enabled).
- Tap **Validate** — review warnings (e.g. outside refund window).
- Tap **Confirm** — return is created, stock and accounting processed.

### 6. Voucher issuance

For voucher refunds:

- A voucher popup shows barcode and balance.
- Print the voucher receipt (manual or auto-print per settings).

![Voucher popup](images/placeholder-pos-voucher-popup.png)

**Example voucher barcode:** `VCH/RV/2026/00042`

---

## Redeeming a voucher at payment

### 1. Build the sale order as usual

Add products and proceed to the **Payment** screen.

### 2. Open the voucher panel

On the payment screen, use **Scan Voucher** or enter the voucher barcode.

![Payment vouchers panel](images/placeholder-pos-payment-vouchers.png)

### 3. Apply voucher amount

- **Full redemption:** apply entire remaining balance.
- **Partial redemption:** enter amount (if allowed by settings).
- **Multiple vouchers:** scan additional vouchers (if allowed).

### 4. Complete payment

Settle any remaining balance with cash, card, or other payment methods.

### Duplicate prevention

The system blocks:

- Redeeming the same voucher twice on one order
- Using multiple vouchers when disabled in settings
- Redeeming expired or cancelled vouchers

---

## Processing an exchange

### 1. Open Exchange screen

Tap **Exchange** from the product screen.

![Exchange screen](images/placeholder-pos-exchange-screen.png)

### 2. Return leg

- Find and select the original order (same as return flow).
- Choose lines and quantities to return.

### 3. Replacement leg

- Add new products to the cart (replacement items).
- POS creates a replacement sales order.

### 4. Settlement

The exchange calculates the **difference**:

- Customer **pays** if replacement costs more
- Customer **receives voucher or refund** if return value is higher
- **Balanced** when amounts match

### 5. Complete

Confirm the exchange. Print the exchange receipt if needed.

---

## Using barcodes

### Supported scan types

| Scan type | Example | Action |
|-----------|---------|--------|
| Product EAN | `5901234123457` | Add/find product or locate orders with that product |
| Voucher | `VCH/RV/2026/00042` | Open voucher validation or payment |
| Return doc | `RET/2026/00015` | Look up return document |
| Order reference | Receipt number | Open order for return |

Scanners act as keyboard input — focus the search field and scan.

### Barcode action popup

When auto-detect is enabled, ambiguous scans may show an action popup to choose **Product**, **Voucher**, **Return**, or **Order**.

---

## Manager tasks

### Cancel a voucher

1. Backend: search **Return Vouchers** (or open from return document).
2. Use **Cancel Voucher** (Manager permission).
3. Cannot cancel fully redeemed vouchers.

### Cash refunds

Requires **Cash Refund** group and **Allow Cash Refund** setting.

### View reports

**Point of Sale → Reporting → Returns & Exchanges:**

- Dashboard
- Return / Voucher / Exchange reports
- Customer, employee, daily, monthly breakdowns
- Sales vs Return analysis

![Report dashboard](images/placeholder-report-dashboard.png)

### Export

From list views, use **Export Excel** or **Export PDF** server actions (Manager).

---

## Common scenarios

### Scenario A — Defective item, equal exchange

1. Customer bought jeans (€50), wants different size (€50).
2. Exchange → return original jeans → add new size.
3. Difference €0 → confirm exchange.

### Scenario B — Partial return with voucher

1. Customer bought 3 shirts, returns 1.
2. Return → select order → qty `1` → refund method **Voucher**.
3. Customer uses voucher on next visit at payment screen.

### Scenario C — Return outside policy window

1. Sale is 45 days old; `max_refund_days = 30`.
2. Validation shows **approval required** warning.
3. Manager reviews and proceeds if appropriate.

### Scenario D — No receipt

If `require_receipt = True`, confirmation is blocked until **Has receipt** is checked or manager overrides policy.

---

## Receipts

Print from:

- POS after return/voucher/exchange (auto or manual)
- Backend document form → **Print Receipt**

Widths: **58 mm** or **80 mm** per configuration.

---

## Offline behaviour

Return, voucher, and exchange RPC calls require network connectivity. When offline, the POS shows an **offline** error — retry when connection is restored. Returns are **not** queued offline in the current version.

---

## Glossary

| Term | Meaning |
|------|---------|
| **Return document** | `cb.pos.return` — backend record of a return |
| **Voucher** | `cb.pos.return.voucher` — store credit instrument |
| **Exchange** | `cb.pos.exchange` — links return + replacement order |
| **Disposition** | What happens to returned stock (restock/quarantine/scrap) |
| **POS reference** | Receipt number printed on customer receipt |
