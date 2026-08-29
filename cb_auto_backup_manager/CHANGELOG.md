# Changelog

All notable versions of CB Auto Backup Manager (Odoo 19).

## 19.0.13.0.0 — 2026-08-29

Odoo Apps Store release packaging (USD 9.99).

- Manifest: `price`, `currency`, `support`, carousel `images`
- Apps Store description page (`static/description/index.html`)
- Build script `tools/build_apps_store_zip.ps1` / `.sh`
- Publishing guide `PUBLISH_APPS_STORE.md`, screenshot list `SCREENSHOTS.md`
- UI display names for dashboard, settings, wizards, and logs (no `model,id` in breadcrumbs)

## 19.0.12.0.0 — 2026-08-16

Google Drive storage with OAuth and Drive API upload/download.

- Connect Google Drive (OAuth Client ID/Secret, refresh token, `drive.file` scope)
- Resumable ZIP/ENC upload, download, list, and trash (not permanent delete)
- Plan activation accepts Local, SFTP, and connected Google Drive destinations
- Redirect URI field for Google Cloud Console
- Mocked provider tests; no live Google credentials are stored in the module

## 19.0.11.0.0 — 2026-08-14

Odoo-compatible backup ZIP format for download / restore on another server.

- New backups use plain `dump.sql` + `filestore/` (same layout Odoo Database Manager expects)
- Still includes `backup_manifest.json` for this module
- Verify / Test Restore accept both `dump.sql` and legacy `database.dump`
- Encrypted `.enc` archives are unchanged (decrypt before Odoo web restore)

## 19.0.10.0.0 — 2026-08-13

Release hardening for Apps Store packaging.

- Documentation: README, User Guide, changelog, license, Apps Store copy, release checklist
- Manifest metadata: CodeBraze author/website, honest Google Drive wording
- Scheduler continues after an individual plan failure
- Retention continues after an individual destination failure
- Explicit `shell=False` on `pg_dump`
- Clearer PostgreSQL dump/restore error messages
- History filter for encrypted backups
- QA coverage for 5/10 backups per day, 00:00/23:59, timezone conversion, retention windows

## 19.0.9.0.0

Optional AES-256-GCM encryption of completed backup archives.

- Encryption profiles with password confirmation
- SHA-256 of the final `.enc` artifact
- Restore/verify decryption flow
- Dashboard encryption coverage

## 19.0.8.0.0

Backup verification and temporary restore testing.

- Verify Only and temporary database restore
- ZIP path-traversal protection
- Current-database and plan-database drop protection
- Restore logs

## 19.0.7.0.0

Monitoring dashboard, KPIs, and cleanup visibility.

## 19.0.6.0.0

Native Odoo notifications for backup and cleanup events.

## 19.0.5.0.0

Production SFTP provider with streaming upload/download and host-key verification.

## 19.0.4.0.0

Scheduling UX: Backups Per Day, multiple times, occurrence duplicate protection.

## 19.0.3.0.0

Retention policy and automatic local cleanup with audit logs.

## 19.0.2.0.0

Backup engine, ZIP packaging, Local storage, destination results, Google Drive stub.

## 19.0.1.0.0

Foundation: Backup Plans, schedules, security groups, single scheduler cron.

## Not in this product

These are intentionally out of scope:

- Live production database overwrite
- Automatic Odoo / nginx / systemd restart
- Incremental or differential backups
- AWS S3, Azure Blob, Dropbox
