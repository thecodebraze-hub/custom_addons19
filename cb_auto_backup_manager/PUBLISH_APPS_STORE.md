# Build Odoo Apps Store ZIP — CB Auto Backup Manager

Creates a clean ZIP ready to upload at [apps.odoo.com](https://apps.odoo.com).

## Prerequisites

1. Capture real screenshots into `static/description/` (see `SCREENSHOTS.md`).
2. Python 3 and PowerShell on Windows (or use the bash variant below).

## Windows

```powershell
cd D:\Odoo_Developments\odoo19\custom_addons\cb_auto_backup_manager
powershell -ExecutionPolicy Bypass -File tools\build_apps_store_zip.ps1
```

Output: `dist/cb_auto_backup_manager-19.0.13.0.0.zip`

## Linux / macOS

```bash
cd custom_addons/cb_auto_backup_manager
bash tools/build_apps_store_zip.sh
```

## What the script excludes

- `__pycache__`, `*.pyc`, `.git`, `.env`, logs, local backup files (`.zip`, `.enc`)
- `dist/` output folder

## After building

1. Log in to [apps.odoo.com](https://apps.odoo.com) as **CodeBraze** publisher.
2. Create or update module **CB Auto Backup Manager** (`cb_auto_backup_manager`).
3. Upload the ZIP.
4. Set **Price: USD 9.99** (manifest already includes `price` / `currency`).
5. Paste short and long description from `APPS_STORE.md`.
6. Submit for review.

## Support contact

- Website: https://www.codebraze.com
- Email: info@codebraze.com

Do not include encryption secrets, SSH keys, or Google OAuth credentials in the package or screenshots.
