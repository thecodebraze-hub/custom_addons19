# Odoo Apps Store copy — CB Auto Backup Manager

**Price:** USD **9.99**  
**Publisher:** CodeBraze (PVT) Ltd  
**Support:** info@codebraze.com  
**Website:** https://www.codebraze.com  
**License:** OPL-1  
**Odoo version:** 19.0  

Use this text on the Apps listing at [apps.odoo.com](https://apps.odoo.com). Do not claim live production restore, AWS S3, Azure, or Dropbox.

---

## App title

CB Auto Backup Manager

## Short description (≤ 200 characters suggested)

Automated PostgreSQL and filestore backups for Odoo 19 — Local, SFTP, Google Drive, scheduling, retention, encryption, and safe restore testing.

## Long description

CB Auto Backup Manager backs up selected PostgreSQL databases and their Odoo filestore on the same Odoo 19 server.

Backup Administrators define Backup Plans: which database to dump, how many backups to run per day, at which times, how long to keep files, and which Storage Destinations receive the archive.

Each run packages a PostgreSQL SQL dump (`dump.sql`), the filestore, and a backup manifest into a ZIP (or an optional AES-256 encrypted container). SHA-256 is recorded on Backup History for the final artifact.

Archives can be delivered to one or more destinations. If some destinations succeed and others fail, history is marked Partial so failures are visible.

Google Drive uses OAuth (Client ID/Secret) and the Drive API. After Connect Google Drive, backups upload to a named folder with database/plan subfolders.

Verification checks ZIP integrity, required members, and checksums. Test Restore loads a temporary PostgreSQL database created by this module. It never drops or overwrites the current Odoo database.

Plain ZIP backups can be restored on another Odoo 19 server with Database Manager → Restore Database.

## Feature bullets

- Backup Plans with database selection on the same Odoo server
- Backups Per Day with daily, weekly, and monthly times
- Local Server, SFTP, and Google Drive storage (multiple destinations per plan)
- Odoo-compatible ZIP (`dump.sql` + filestore)
- SHA-256 checksums and ZIP integrity checks
- Optional AES-256-GCM encryption profiles
- Retention cleanup with Cleanup Logs
- Native Odoo notifications and monitoring Dashboard
- Backup verification and temporary restore testing
- Backup Administrator and Backup Operator access rights

## Supported versions

- Odoo 19 Community and Enterprise (depends on `base` and `mail` only)

## Storage providers

- Local Server — implemented
- SFTP — implemented (Paramiko, host-key verification, streamed transfer)
- Google Drive — implemented (OAuth, Drive API upload/download, trash for retention)

## Pricing (publisher portal)

| Field | Value |
|-------|-------|
| Price | **9.99** |
| Currency | **USD** |
| License | **OPL-1** (Odoo Proprietary) |

Manifest fields: `"price": 9.99`, `"currency": "USD"`.

## Submission checklist

- [ ] Real screenshots in `static/description/` (see `SCREENSHOTS.md`)
- [ ] Run `tools/build_apps_store_zip.ps1` → upload ZIP from `dist/`
- [ ] Paste short + long description above
- [ ] Confirm support email **info@codebraze.com**
- [ ] Category: **Administration**
- [ ] No secrets in screenshots or package

## Screenshots (carousel + index.html)

1. Dashboard  
2. Backup Plan  
3. Backup Times / schedule  
4. Storage Destinations  
5. SFTP configuration  
6. Google Drive configuration  
7. Backup History  
8. Verify Backup  
9. Test Restore  
10. Encryption Profile  

Do not mock live production restore or fake Google Drive uploads.
