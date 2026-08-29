#!/usr/bin/env bash
set -euo pipefail
MODULE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODULE_NAME="$(basename "$MODULE_ROOT")"
VERSION="$(grep -E "^\s*'version'" "$MODULE_ROOT/__manifest__.py" | head -1 | sed "s/.*'\([^']*\)'.*/\1/")"
DESC="$MODULE_ROOT/static/description"
COVER="$DESC/cover.png"
[[ -f "$COVER" ]] || cp "$DESC/icon.png" "$COVER"
for img in banner.png screenshot_dashboard.png screenshot_plan.png screenshot_schedule.png \
  screenshot_storage_list.png screenshot_sftp.png screenshot_google_drive.png screenshot_history.png \
  screenshot_verify.png screenshot_restore_test.png screenshot_encryption.png; do
  if [[ ! -f "$DESC/$img" ]]; then
    echo "WARN: missing $img — using cover placeholder" >&2
    cp "$COVER" "$DESC/$img"
  fi
done
DIST="$MODULE_ROOT/dist"
mkdir -p "$DIST"
ZIP="$DIST/${MODULE_NAME}-${VERSION}.zip"
rm -f "$ZIP"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
rsync -a --exclude dist --exclude .git --exclude __pycache__ --exclude '*.pyc' --exclude .venv \
  --exclude '*.log' --exclude '*.enc' --exclude .env \
  "$MODULE_ROOT/" "$TMP/$MODULE_NAME/"
(cd "$TMP" && zip -rq "$ZIP" "$MODULE_NAME")
echo "Built: $ZIP"
