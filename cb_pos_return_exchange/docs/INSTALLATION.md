# Installation Guide

**Module:** `cb_pos_return_exchange`  
**Odoo version:** 19.0

---

## Prerequisites

### Odoo modules (auto-installed as dependencies)

- `point_of_sale`
- `stock`
- `sale`
- `account`
- `product`
- `mail`
- `web`

### System requirements

- PostgreSQL database (Odoo 19 supported version)
- Python environment matching your Odoo 19 installation
- `custom_addons` path includes this module directory

### Recommended setup

- At least one **POS Configuration** with a warehouse and stockable products
- POS users assigned to **Point of Sale / User** plus **POS Return & Exchange** role groups

---

## Step 1 — Add module to addons path

Ensure your Odoo configuration includes the folder containing this module:

```ini
[options]
addons_path = /path/to/odoo/addons,/path/to/enterprise,/path/to/custom_addons
```

Restart the Odoo server after changing `addons_path`.

---

## Step 2 — Update apps list

1. Log in as Administrator.
2. Enable **Developer Mode** (Settings → Activate Developer Mode).
3. Go to **Apps** → **Update Apps List**.

![Apps update](images/placeholder-apps-install.png)

---

## Step 3 — Install the module

**From the UI**

1. Remove the *Apps* filter if needed.
2. Search for **CodeBraze POS Return & Exchange**.
3. Click **Install**.

**From the command line**

```bash
python odoo-bin -c odoo19.conf -d YOUR_DATABASE \
  -i cb_pos_return_exchange --stop-after-init
```

**Upgrade an existing installation**

```bash
python odoo-bin -c odoo19.conf -d YOUR_DATABASE \
  -u cb_pos_return_exchange --stop-after-init
```

---

## Step 4 — Post-install hook

On install, `post_init_hook` runs automatically and links every existing `pos.config` record to a per-POS return settings record via `_cb_ensure_return_settings()`.

No manual action is required unless you create new POS configurations later — opening the POS config form creates settings on demand.

---

## Step 5 — Assign security groups

Go to **Settings → Users & Companies → Users**, open each POS cashier/manager, and set **POS Return & Exchange**:

| Role | Typical user |
|------|----------------|
| **Cashier** | Front-line staff — returns, redeem/print vouchers |
| **Manager** | Store manager — cash refunds, cancel vouchers, reports, settings |
| **Administrator** | IT / head office — full access including advanced settings |

![User access rights](images/placeholder-user-access-rights.png)

---

## Step 6 — Verify installation

### Backend checks

- **Point of Sale → Configuration → Return & Exchange Settings** menu exists.
- Open any **POS Configuration** → **Returns & Exchanges** tab is visible (Manager+).
- **Point of Sale → Reporting → Returns & Exchanges** submenu appears (Manager+).

### POS checks

1. Open a POS session.
2. Confirm **Return** and **Exchange** buttons appear on the product screen (when module is enabled).
3. Process a test sale, then open **Return** and search by receipt reference.

### Automated tests (optional)

```bash
python odoo-bin -c odoo19.conf -d YOUR_DATABASE \
  --test-enable --stop-after-init \
  -u cb_pos_return_exchange \
  --test-tags=cb_pos_return_exchange
```

All tests should pass (some accounting tests skip when invoicing is not configured).

---

## Demo data (optional)

Demo data loads **only when the database is created with demo enabled** (`Load demonstration data` checkbox).

Includes:

- 3 demo customers (Alice, Bob, Carol)
- 3 demo products (T-shirt, Jeans, Sneakers)
- Sample POS orders, returns, vouchers, and an exchange (via `load_demo_data()`)

Demo is idempotent — reloading does not duplicate records (checked via `demo_return_voucher_done` marker).

To use demo on a new database:

```bash
python odoo-bin -c odoo19.conf -d NEW_DB \
  -i cb_pos_return_exchange --without-demo=False --stop-after-init
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Module not in Apps list | Verify `addons_path`, update apps list, check folder name is `cb_pos_return_exchange` |
| Return buttons missing in POS | Enable **Module** on company/POS settings; hard-refresh POS (`Ctrl+Shift+R`) |
| Permission errors | Assign **Cashier** or **Manager** group; check granular groups for cash refund |
| Stock not updated | Enable **Auto-Validate Return Pickings**; confirm products are storable |
| Tests won't run | Pass `-d DATABASE` — Odoo skips tests without a database name |

---

## Uninstall notes

Uninstalling removes module data (returns, vouchers, exchanges, settings). Export reports or backup the database before uninstalling in production.
