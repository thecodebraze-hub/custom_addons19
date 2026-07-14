# Upgrade Guide

Instructions for upgrading **CodeBraze POS Return & Exchange** between versions on Odoo 19.

---

## Before you upgrade

1. **Backup the database** (pg_dump or Odoo backup).
2. Note the current module version: **Settings → Apps → CodeBraze POS Return & Exchange**.
3. Read the version notes below for breaking changes.
4. Test on a staging copy before production.

---

## Standard upgrade command

```bash
python odoo-bin -c odoo19.conf -d YOUR_DATABASE \
  -u cb_pos_return_exchange --stop-after-init
```

With tests:

```bash
python odoo-bin -c odoo19.conf -d YOUR_DATABASE \
  --test-enable --stop-after-init \
  -u cb_pos_return_exchange \
  --test-tags=cb_pos_return_exchange
```

**From the UI:** Apps → module → **Upgrade** (Developer Mode required).

---

## Post-upgrade steps

1. **Hard-refresh POS browsers** (`Ctrl+Shift+R`) to load updated OWL assets.
2. Verify **Return & Exchange Settings** — new fields get defaults from `cb_pos_return_config_data.xml`.
3. Open each active **POS Configuration** and confirm the Returns & Exchanges tab.
4. Run a test return and voucher redemption in a staging session.
5. Check **Point of Sale → Reporting → Returns & Exchanges** menus load.

`post_init_hook` re-runs on upgrade and ensures all `pos.config` records have linked settings.

---

## Version history

| Version | Highlights |
|---------|------------|
| **19.0.1.15.0** | Production hardening: qty validation, API company checks, Odoo 19 XML (`group_ids`), SQL view fix, OWL bug fixes, Apps Store assets |
| **19.0.1.14.0** | Automated test suite (returns, voucher, exchange, accounting, inventory, barcode, API, security, performance, edge cases) |
| **19.0.1.13.0** | Demo data loader (customers, products, orders, returns, vouchers, exchange) |
| **19.0.1.12.0** | POS Configuration tab, `module_enabled`, per-POS settings override, multi-voucher / partial voucher enforcement |
| **19.0.1.11.0** | Analytics reports — pivot, graph, dashboard, Excel/PDF export |
| **19.0.1.10.0** | QWeb thermal receipts (58/80 mm), auto-print hooks |
| **19.0.1.x** | POS OWL frontend, barcode handler, voucher payment panel |
| **19.0.1.0.0** | Initial release — models, API, security, stock & accounting integration |

---

## Migration notes

### 19.0.1.10.0 → Receipt templates

- New report actions for return/voucher/exchange receipts.
- Set `receipt_paper_width` in settings (default **80 mm**).
- No data migration required.

### 19.0.1.12.0 → POS settings split

- Company-wide config in **Return & Exchange Settings** menu.
- Per-POS overrides on `pos.config` form tab.
- `post_init_hook` creates missing per-POS config rows.

**Action:** Review `module_enabled` on each POS after upgrade.

### 19.0.1.11.0 → Reporting models

- New SQL view `cb.pos.sales.return.analysis` — rebuilt on module upgrade.
- Dashboard uses server actions; no manual SQL needed.

### 19.0.1.14.0 → Receipt model inheritance fix

Receipt extensions must inherit existing models (`cb.pos.return`, `cb.pos.return.voucher`, `cb.pos.exchange`) with the abstract mixin — not as separate `cb.pos.return.receipt` models.

If you customized `cb_pos_return_receipt.py`, merge custom print logic into `_inherit` extensions on the base models.

### Odoo 19 specifics

- `report_count` on report models uses `store=True` default (not `@api.depends("id")`).
- Security uses `res.groups.privilege` for POS Return & Exchange roles.
- POS frontend uses Odoo 19 OWL POS (`point_of_sale._assets_pos`).

---

## Downgrade

Odoo does not support clean module downgrade. Restore from backup if you must revert.

---

## Custom module dependencies

If another module depends on `cb_pos_return_exchange`:

```python
"depends": ["cb_pos_return_exchange"],
```

After upgrading this module, upgrade dependents:

```bash
python odoo-bin -c odoo19.conf -d YOUR_DATABASE \
  -u cb_pos_return_exchange,your_custom_module --stop-after-init
```

---

## Troubleshooting upgrades

| Error | Resolution |
|-------|------------|
| `Many2many fields ... use the same table` | Upgrade to ≥ 19.0.1.14.0 receipt fix; restart server |
| `Invalid field` on view | Custom inherited views may reference renamed fields — update XML |
| POS white screen | Clear assets bundle; upgrade `point_of_sale`; check browser console |
| Missing settings menu | User needs `group_cb_pos_modify_settings` |
| Tests fail after upgrade | Run with `--test-tags=cb_pos_return_exchange` and inspect log |

---

## Checklist

- [ ] Database backup completed
- [ ] Module upgraded (`-u cb_pos_return_exchange`)
- [ ] Tests pass (optional but recommended)
- [ ] POS assets refreshed on all terminals
- [ ] Settings reviewed per company/POS
- [ ] Sample return + voucher flow verified
- [ ] Reports accessible to managers
