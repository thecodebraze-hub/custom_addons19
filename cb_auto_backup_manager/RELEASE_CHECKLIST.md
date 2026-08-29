# Release Checklist — CB Auto Backup Manager 19.0.13.0.0 (Apps Store USD 9.99)

Use this list before publishing an Odoo Apps package.

## Apps Store packaging

- [ ] Screenshots captured (`SCREENSHOTS.md`) — replace any placeholders
- [ ] `static/description/index.html` reviewed
- [ ] `price: 9.99` and `currency: USD` in `__manifest__.py`
- [ ] `support: info@codebraze.com` in manifest
- [ ] ZIP built with `tools/build_apps_store_zip.ps1`
- [ ] Uploaded to [apps.odoo.com](https://apps.odoo.com) — price confirmed USD 9.99
- [ ] Listing text from `APPS_STORE.md` pasted

## Installation and lifecycle

- [ ] Odoo 19 installation tested
- [ ] Upgrade tested (existing plans, schedules, storage, history, cleanup logs, encryption profiles remain)
- [ ] Uninstall tested (PostgreSQL databases, filestores, and backup files on disk/SFTP/Drive are not deleted)

## Security and access

- [ ] Security tested
- [ ] Access rights tested (Backup Administrator vs Backup Operator)
- [ ] Current database protection tested
- [ ] No secrets included in source, XML, CSV, README, tests, or screenshots
- [ ] No debug files included (`__pycache__`, `.env`, logs, keys)

## Backup operations

- [ ] Database backup tested
- [ ] Filestore backup tested
- [ ] Local storage tested
- [ ] SFTP tested
- [ ] Google Drive Connect + Test Connection + Backup Now tested
- [ ] Multiple destinations tested (including partial success)
- [ ] Multiple backups/day tested
- [ ] Retention tested

## Operations UI

- [ ] Notifications tested
- [ ] Dashboard tested
- [ ] Backup verification tested
- [ ] Temporary restore tested
- [ ] Encryption tested

## Documentation and package

- [ ] README complete
- [ ] User Guide complete
- [ ] Changelog complete
- [ ] Manifest verified (no example.com, honest feature list)
- [ ] Final package cleaned (no `.git`, pycache, credentials, local backup archives)

## Apps Store screenshots (capture from a real database)

Recommended, using the actual UI only:

1. Dashboard
2. Backup Plan
3. Schedule configuration (Backup Times)
4. Storage Destinations list
5. SFTP configuration
6. Google Drive configuration (Connect / Redirect URI)
7. Backup History
8. Backup verification wizard
9. Restore Test wizard
10. Encryption Profile

Do not mock screenshots of live production restore.
