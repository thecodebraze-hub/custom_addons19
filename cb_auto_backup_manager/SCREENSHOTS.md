# Apps Store screenshots — CB Auto Backup Manager

Capture these PNG files from a **real Odoo 19 database** with the module installed.
Save each file under `static/description/` using the exact filename below.

| File | What to capture |
|------|-----------------|
| `cover.png` | Branded cover (1280×720 or similar). Replace the icon copy if you have a designer cover. |
| `banner.png` | Apps carousel banner (same as cover or wide crop). |
| `screenshot_dashboard.png` | Auto Backup Manager → Dashboard (KPIs visible) |
| `screenshot_plan.png` | Backup Plans → open one active plan |
| `screenshot_schedule.png` | Plan form → Backup Times tab |
| `screenshot_storage_list.png` | Storage Destinations list |
| `screenshot_sftp.png` | SFTP destination form (blur/mask any real host keys if needed) |
| `screenshot_google_drive.png` | Google Drive page with Redirect URI (no real Client Secret visible) |
| `screenshot_history.png` | Backup History list with at least one Success row |
| `screenshot_verify.png` | Verify Backup wizard |
| `screenshot_restore_test.png` | Test Restore wizard |
| `screenshot_encryption.png` | Configuration → Encryption Profiles |

## Rules (Odoo Apps review)

- Use the actual module UI only — do not mock fake data in Photoshop.
- Do not show real passwords, private keys, refresh tokens, or encryption secrets.
- Use a demo database name (e.g. `odoo19_demo`) if possible.
- PNG format, readable text, no personal customer data.

## Quick check before upload

```powershell
$desc = "static\description"
$required = @(
  "cover.png","banner.png","screenshot_dashboard.png","screenshot_plan.png",
  "screenshot_schedule.png","screenshot_storage_list.png","screenshot_sftp.png",
  "screenshot_google_drive.png","screenshot_history.png","screenshot_verify.png",
  "screenshot_restore_test.png","screenshot_encryption.png","developed_by.png","icon.png"
)
$required | ForEach-Object { if (-not (Test-Path (Join-Path $desc $_))) { Write-Warning "Missing: $_" } }
```

Replace placeholder images (copies of `cover.png`) with real screenshots before final submission.
