# CB Auto Backup Manager

Automated PostgreSQL database and Odoo filestore backups for **Odoo 19** servers.

Product: **CB Auto Backup Manager**  
Technical name: `cb_auto_backup_manager`  
Publisher: **CodeBraze (PVT) Ltd**  
License: **OPL-1**  
Version: **19.0.13.0.0** · **USD 9.99** (Odoo Apps Store)

This module backs up databases that exist on the **same Odoo server**. It does not overwrite the live database, restart Odoo, or provide one-click disaster-recovery restore into production.

## 1. Product Overview

CB Auto Backup Manager lets Backup Administrators define Backup Plans: which PostgreSQL database to dump, when to run, how long to keep files, and which Storage Destinations receive the archive.

Each successful run packages:

- a PostgreSQL plain SQL dump (`dump.sql`) — same format as Odoo Database Manager
- the Odoo filestore
- `backup_manifest.json`

into a ZIP (or an AES-256 encrypted `.enc` container). SHA-256 is stored on Backup History for the **final** artifact.

Plain ZIP backups can be downloaded and restored on another Odoo 19 server with **Database Manager → Restore Database**. Encrypted `.enc` files must be decrypted first (or use Verify / Test Restore in this module).

## 2. Features

- Backup Plans with database selection
- Backups Per Day with daily, weekly, and monthly times
- Local Server, SFTP, and Google Drive storage
- Multiple destinations per plan, with destination-level results
- ZIP integrity and SHA-256 checksums
- Optional AES-256-GCM encryption profiles
- Retention cleanup with Cleanup Logs
- Native Odoo notifications and a monitoring Dashboard
- Backup verification and temporary restore testing
- Concurrency protection and a single scheduler cron

## 3. Requirements

- Odoo 19
- PostgreSQL with `pg_dump` available to the Odoo process
- Python package `paramiko` for SFTP (`pip install paramiko`)
- `cryptography` (already provided by Odoo 19) for encryption
- Google Cloud OAuth client (Web application) and Google Drive API for Drive destinations

## 4. Installation

1. Copy `cb_auto_backup_manager` into your addons path.
2. Install Paramiko on the Odoo server if you will use SFTP.
3. Update the Apps list and install **CB Auto Backup Manager**.
4. Assign **Backup Administrator** or **Backup Operator**.

Uninstalling the module does **not** delete backup files on disk, SFTP, or Google Drive. Odoo only removes module data records (plans, history, logs). Keep those files if you still need them.

## 5. Configuration

Configuration is **server-level**, not per Odoo company. Secrets are restricted by security groups, not by `res.company`.

Typical order:

1. Create Storage Destinations
2. Create Encryption Profiles if needed
3. Create a Backup Plan
4. Activate the plan

## 6. Backup Plans

A Backup Plan selects one PostgreSQL database, retention days, Backups Per Day, schedules, destinations, and optional encryption.

Plans start in **Draft**. Only Backup Administrators can Activate or Deactivate.

## 7. Scheduling

`backups_per_day` is the number of automatic runs on each applicable day. Manual **Backup Now** is independent.

Times are evaluated in the plan's IANA timezone. One cron runs every minute, skips inactive plans, and will not run the same plan+schedule+slot twice.

## 8. Storage Destinations

Each plan can use several destinations. One backup artifact is delivered to each active destination.

Overall history status:

- **Success** — every destination succeeded
- **Partial** — the archive was created and at least one destination succeeded while another failed
- **Failed** — nothing usable was stored

## 9. Local Storage

Use an absolute directory on the Odoo server. The module stores files under `<root>/<database>/plan_<id>/`. Validate Storage before activation.

## 10. SFTP

Configure host, port, username, remote absolute path, and host-key fingerprint. Authenticate with a password or SSH private key (Backup Administrators only). Uploads stream in chunks and use a temporary `.uploading` name, then rename.

## 11. Google Drive

Create a Google Cloud OAuth **Web application** client, enable the Google Drive API, and add the Redirect URI shown on the storage form (`{web.base.url}/cb_auto_backup_manager/google_drive/oauth/callback`).

Save Client ID and Client Secret, click **Connect Google Drive**, complete Google consent, then **Test Connection**. Backups are stored under a named folder in My Drive (default `Odoo Backups`) with `database/plan_<id>` subfolders.

The module uses the `drive.file` scope (files it creates). Disconnect clears tokens in Odoo; files already uploaded to Drive remain until you delete them in Drive or with this module’s retention (trash, not permanent delete).

## 12. Retention

Retention is in days. Cleanup deletes only files this module can identify (filename + manifest or encrypted header) inside the plan directory. Unrelated files, other databases, and other plans are skipped. Backup History records are kept.

## 13. Notifications

Scheduled results and cleanup failures can be sent to Discuss/inbox. Manual Backup Now, Cleanup Now, and Test Connection also show an on-screen notification. Credentials are never included.

## 14. Dashboard

The dashboard shows KPIs, today's backups, recent activity, failures, next backup, storage totals from history, encryption coverage, verification/restore status, and cleanup summary. It does not scan remote disks on load.

## 15. Backup Verification

**Verify Backup** checks that the archive exists, the ZIP (or decrypted ZIP) is valid, the manifest, dump, and filestore are present, and the SHA-256 matches. Operators and administrators can verify.

## 16. Test Restore

**Test Restore** is Backup Administrators only. It restores into a temporary PostgreSQL database named like `backup_test_<database>_<timestamp>` and validates tables in that copy. It never drops or overwrites the current Odoo database.

## 17. Encryption

Optional per plan. Create an Encryption Profile (password + confirmation), enable encryption on the plan, and select the profile.

The ZIP is encrypted with AES-256-GCM after integrity checks. History checksums the `.enc` file. Restore requires the secret.

**Store the encryption secret outside this Odoo server. CodeBraze cannot recover an encrypted backup if the secret is permanently lost.**

## 18. Security

- Backup Administrator: full configuration, cleanup, test restore, encryption profiles
- Backup Operator: view operations, run permitted backups, verify archives; cannot read secrets or change critical configuration
- No `shell=True` / `os.system()`
- ZIP path traversal blocked
- Temporary restore databases are dropped only if this module created them
- SFTP host-key verification is required

## 19. Troubleshooting

| Symptom | What to check |
|---|---|
| Plan will not activate | Database exists, schedules match Backups Per Day, each destination validates (Google Drive must be connected) |
| Backup failed | PostgreSQL `pg_dump`, filestore path, destination permissions |
| SFTP failed | Host key, credentials, remote path, disk quota |
| Google Drive failed | Redirect URI matches `web.base.url`, Drive API enabled, Connect completed, token not revoked |
| Encryption failed | Profile password is set and at least 12 characters |
| Decrypt failed | Secret does not match; file may be corrupted |
| Duplicate backups | Confirm the slot was not already recorded; only one cron should exist |

## 20. Uninstall behavior

Uninstall removes the module's Odoo records. It does **not** delete:

- PostgreSQL databases
- Odoo filestores
- local ZIP/ENC files
- SFTP remote files
- Google Drive files already uploaded

Copy or archive those files before uninstall if you still need them.

## 21. Upgrade behavior

Upgrading from earlier 19.0.x versions keeps Backup Plans, Schedules, Storage Destinations, Backup History, Cleanup Logs, and Encryption Profiles. New fields receive safe defaults (encryption off, verification never tested).

## 22. Limitations

- No live production database overwrite restore
- No automatic Odoo / nginx / systemd restart
- No incremental or differential backups
- No AWS S3, Azure, or Dropbox
- Test restore is synchronous in the HTTP worker
- Secrets stored in Odoo are access-controlled, not HSM-backed
- Temporary files are removed with normal filesystem delete

## 23. Support

CodeBraze (PVT) Ltd  
Website: https://www.codebraze.com  
Do not send encryption secrets or SSH private keys in support tickets.
