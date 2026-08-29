# CB Auto Backup Manager — User Guide

This guide is for an Odoo administrator installing and operating CB Auto Backup Manager on Odoo 19.

Do not put real passwords, SSH keys, or encryption secrets in notes, screenshots, or tickets.

## 1. Install the module

1. Place `cb_auto_backup_manager` in the Odoo addons path.
2. If you will use SFTP, install Paramiko on the server: `pip install paramiko`
3. Restart Odoo, Update Apps List, and install **CB Auto Backup Manager**.
4. In Users, assign **Backup Administrator** (full setup) or **Backup Operator** (run/verify only).

## 2. Create a Storage Destination

Open **Auto Backup Manager → Storage Destinations → New**.

Give it a clear name, for example `Local Server Backups`.

## 3. Configure Local, SFTP, or Google Drive

**Local Server**

- Type: Local Server
- Local Path: an absolute directory the Odoo process can write, for example `/var/backups/odoo`

**SFTP**

- Type: SFTP Server
- Host, port, username, remote absolute path
- Authentication: password or private key
- Host Key / Fingerprint: required. Use **Test Connection**, confirm the fingerprint out-of-band, then save it.

**Google Drive**

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project (or pick one).
2. Enable **Google Drive API**.
3. Create **OAuth client ID** of type **Web application**.
4. Copy the **Redirect URI** from the storage form and add it as an authorized redirect URI.
5. Paste **Client ID** and **Client Secret**, save the destination, then click **Connect Google Drive**.
6. Sign in with the Google account that should own the backups. Grant access.
7. Confirm **Google Account** is filled and status is Connected, then click **Test Connection**.
8. Set **Google Drive Folder** (default `Odoo Backups`). Nested folders per database/plan are created automatically.

If Google does not return a refresh token, revoke the app in the Google account and Connect again.

## 4. Test storage

- Local: **Validate Storage**
- SFTP: **Test Connection**
- Google Drive: **Connect Google Drive**, then **Test Connection**

Fix errors before activating a plan. Operators cannot change storage credentials.

## 5. Create a Backup Plan

Open **Auto Backup Manager → Backup Plans → New**.

## 6. Select the database

Choose the PostgreSQL database that exists on **this** Odoo server. The list comes from Odoo/PostgreSQL, not from a hard-coded name.

## 7. Set Backups Per Day

Set how many automatic backups should run on each scheduled day, for example `3`.

**Backup Now** is not limited by this number.

## 8. Set backup times

On **Backup Times**, add one line per run.

Example for three daily backups:

- 06:00
- 14:00
- 23:00

Daily active lines must match Backups Per Day. Weekly and monthly lines keep their weekday or month-day, and each selected day must also match that count.

Set **Schedule Timezone** to the IANA zone you want those clock times to use.

## 9. Set retention days

Enter how many days to keep backup files, for example `30`. Cleanup never deletes history rows, only identified backup files that are older than the cutoff.

## 10. Configure notifications

On the Notifications page:

- Choose whether to notify on success, failure, partial success, and cleanup failure.
- Select users who should receive Discuss notifications (Backup Administrators and Operators only).

## 11. Enable encryption (optional)

1. Open **Configuration → Encryption Profiles**.
2. Create a profile, enter the password twice (at least 12 characters).
3. Store that password in your company password manager. CodeBraze cannot recover it later.
4. On the Backup Plan, enable Encryption and select the profile.

Leave encryption disabled if you do not need encrypted archives.

## 12. Activate the plan

Click **Activate**. Activation checks the database, schedules, destinations, and encryption profile.

A Google Drive destination must be connected (refresh token present) and must pass Test Connection / activation live checks. You can use Google Drive alone or together with Local/SFTP.

## 13. Run Backup Now

Click **Backup Now**. Wait for the on-screen notification.

Then open **Backup History** and confirm:

- Status Success or Partial
- File name `.zip` or `.enc`
- Destination results for each storage

## 14. View Backup History

Each run shows duration, size, checksum, destinations, verification status, and restore-test status.

**Partial** means the archive was created but at least one destination failed. Fix that destination; do not ignore it.

## 15. Verify a backup

Open a history record → **Verify Backup**.

For encrypted backups, type the encryption secret. Verification does not create a database.

## 16. Test Restore

Backup Administrators only.

Open a history record → **Test Restore**. Keep **Cleanup After Test** enabled unless you intentionally need the temporary database for inspection.

This creates `backup_test_...` and then drops it after checks. It will refuse to touch the current Odoo database.

## 16b. Download ZIP and restore on another Odoo server

New backups (module 19.0.11+) use the same ZIP layout as Odoo Database Manager:

- `dump.sql`
- `filestore/`
- `backup_manifest.json` (extra; safe for Odoo restore)

Steps:

1. Copy the `.zip` from Local path (for example `/opt/backup/...`), SFTP, or Google Drive (download from Drive or from Backup History if the file is local).
2. On the other server open **Database Manager** (or `/web/database/manager`).
3. **Restore Database** and upload that ZIP.
4. Choose a **new** database name (do not overwrite a live DB casually).

Notes:

- Encrypted `.enc` files cannot be restored in Database Manager until decrypted.
- Older module backups that contain `database.dump` (not `dump.sql`) still work inside this module’s Verify / Test Restore, but not in Odoo Database Manager.

## 17. Read Cleanup Logs

Open **Cleanup Logs** or the plan's Cleanup Logs page.

Look for deleted vs skipped files. Skipped files include unrelated names, other plans, and files still inside retention.

Use **Cleanup Now** on an active plan to run retention immediately.

## 18. Monitor the dashboard

Open **Dashboard** for:

- backups today
- recent failures
- next scheduled backup
- storage totals from history
- encryption coverage
- last verification and last test restore

The dashboard does not log into SFTP or Google Drive when it loads.
