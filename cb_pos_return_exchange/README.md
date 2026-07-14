# CodeBraze POS Return & Exchange

**Version:** 19.0.1.15.0  
**Odoo:** 19.0 (Community & Enterprise POS)  
**License:** LGPL-3  
**Author:** [CodeBraze](https://www.codebraze.com)

End-to-end Point of Sale returns, exchanges, and return vouchers with inventory, accounting, barcode support, thermal receipts, analytics, and a full POS OWL frontend.

---

## Features

| Area | Capabilities |
|------|----------------|
| **Returns** | Find original orders, partial returns, restock/quarantine/scrap disposition, cash or voucher refund, audit trail |
| **Vouchers** | Issue, print, partial/full redemption, multi-voucher payment, expiry cron, duplicate prevention |
| **Exchanges** | Return + replacement order linking, balanced settlement, exchange receipts |
| **Inventory** | Return pickings, auto-validation, lot/serial validation |
| **Accounting** | Credit notes on invoiced orders (configurable auto-create/post) |
| **Barcode** | Product, voucher, return, and order lookup; USB/wireless scanner support |
| **POS UI** | Return screen, exchange screen, voucher payment panel, barcode handler |
| **Receipts** | QWeb thermal templates — 58 mm / 80 mm for return, voucher, exchange |
| **Reporting** | Pivot, graph, list, dashboard, Excel/PDF export |
| **Security** | Cashier → Manager → Administrator roles with granular permissions |
| **Tests** | Automated suite covering returns, vouchers, exchanges, accounting, inventory, barcode, API, security, performance, edge cases |

---

## Quick Start

1. Install dependencies: `point_of_sale`, `stock`, `sale`, `account`, `product`, `mail`, `web`.
2. Install module **CodeBraze POS Return & Exchange** from Apps.
3. Assign POS users to **POS Return & Exchange → Cashier** (or Manager).
4. Open **Point of Sale → Configuration → Return & Exchange Settings** and review company defaults.
5. Open your **POS Configuration** → **Returns & Exchanges** tab for per-register overrides.
6. Open a POS session — use **Return** / **Exchange** buttons on the product screen.

See `docs/images/README.md` for recommended screenshot captures.

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Installation Guide](docs/INSTALLATION.md) | Prerequisites, install steps, demo data, verification |
| [Configuration Guide](docs/CONFIGURATION.md) | Company/POS settings, security groups, barcode & receipt options |
| [User Manual](docs/USER_MANUAL.md) | Cashier workflows: returns, vouchers, exchanges, barcodes |
| [Developer Guide](docs/DEVELOPER_GUIDE.md) | Architecture, models, extending the module, running tests |
| [Upgrade Guide](docs/UPGRADE.md) | Version history, migration notes, upgrade commands |
| [API Documentation](docs/API.md) | `cb.pos.return.api` and `cb.pos.exchange` RPC reference |

---

## Module Structure

```
cb_pos_return_exchange/
├── models/          # Business logic, POS API, accounting, stock
├── static/src/app/  # OWL POS frontend (screens, services, popups)
├── views/           # Backend config, reports, POS config tab
├── report/          # QWeb receipts & analytics PDFs
├── security/        # Groups, access rules, record rules
├── data/            # Sequences, cron, server actions
├── demo/            # Optional demo data (DB creation with demo enabled)
├── tests/           # Automated test suite
└── docs/            # This documentation set
```

---

## Running Tests

```bash
python odoo-bin -c odoo19.conf -d YOUR_DATABASE \
  --test-enable --stop-after-init \
  -u cb_pos_return_exchange \
  --test-tags=cb_pos_return_exchange
```

Performance tests use an additional tag:

```bash
--test-tags=cb_pos_return_exchange,cb_pos_performance
```

---

## Support

- **Website:** https://www.codebraze.com  
- **Module technical name:** `cb_pos_return_exchange`

For bugs or feature requests, contact your CodeBraze implementation partner or open an issue in your project repository.
