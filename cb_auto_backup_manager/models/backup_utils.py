# -*- coding: utf-8 -*-
import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

BACKUP_ENGINE_VERSION = '4.0'
BACKUP_FORMAT = 'zip_v1'
BACKUP_FILE_VERSION = '1.0'
# Odoo Database Manager restore expects dump.sql (plain pg_dump).
# Older module versions used PostgreSQL custom-format database.dump.
DATABASE_DUMP_FILENAME = 'dump.sql'
LEGACY_DATABASE_DUMP_FILENAME = 'database.dump'
MANIFEST_FILENAME = 'backup_manifest.json'
FILESTORE_DIRNAME = 'filestore'
MODULE_NAME = 'cb_auto_backup_manager'
PART_FILE_SUFFIX = '.part'
SFTP_UPLOAD_SUFFIX = '.uploading'

_DB_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]{0,62}$')
TEMP_RESTORE_DB_PREFIX = 'backup_test_'
MAX_PG_IDENT_LENGTH = 63
PROTECTED_DATABASE_NAMES = frozenset({'postgres', 'template0', 'template1'})
_ZIP_UNIX_SYMLINK = 0o120000
_ZIP_UNIX_IFMT = 0o170000
_BACKUP_FILENAME_RE = re.compile(
    r'^([a-zA-Z_][a-zA-Z0-9_]{0,62})_(\d{8})_(\d{6})\.(zip|enc)$'
)
_SENSITIVE_PATTERNS = (
    re.compile(r'password\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'passphrase\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'PGPASSWORD\s*=\s*\S+', re.IGNORECASE),
    re.compile(r'-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----', re.IGNORECASE | re.DOTALL),
    re.compile(r'-----BEGIN\s+[A-Z\s]+PRIVATE KEY-----', re.IGNORECASE),
    re.compile(r'(access_token|refresh_token|client_secret|client_id)\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'(encryption_secret|derived_key|aes[-_]?key)\s*[=:]\s*\S+', re.IGNORECASE),
)


class BackupError(Exception):
    """Raised when a backup operation fails."""


def validate_database_name(database_name):
    """Return a stripped database name or raise BackupError."""
    name = (database_name or '').strip()
    if not name:
        raise BackupError('Database name must not be empty.')
    if not _DB_NAME_RE.match(name):
        raise BackupError('Database name contains invalid characters.')
    return name


def generate_backup_filename(database_name, backup_dt=None, encrypted=False):
    """Build a safe backup filename (.zip or .enc)."""
    db_name = validate_database_name(database_name)
    backup_dt = backup_dt or datetime.utcnow()
    timestamp = backup_dt.strftime('%Y%m%d_%H%M%S')
    extension = 'enc' if encrypted else 'zip'
    filename = '%s_%s.%s' % (db_name, timestamp, extension)
    if Path(filename).name != filename:
        raise BackupError('Generated backup filename is invalid.')
    return filename


def build_backup_manifest(
    database_name,
    backup_datetime,
    odoo_version,
    module_version,
    filestore_included,
    filestore_missing=False,
    plan_id=None,
    plan_identifier=None,
    encryption_method=None,
):
    """Build manifest metadata without secrets."""
    manifest = {
        'module_name': MODULE_NAME,
        'module_version': module_version,
        'database_name': database_name,
        'backup_datetime': backup_datetime.isoformat(),
        'odoo_version': odoo_version,
        'backup_format': BACKUP_FORMAT,
        'filestore_included': filestore_included,
        'filestore_missing': filestore_missing,
        'database_dump_filename': DATABASE_DUMP_FILENAME,
        'backup_engine_version': BACKUP_ENGINE_VERSION,
        'backup_file_version': BACKUP_FILE_VERSION,
        'encryption_method': encryption_method or 'none',
    }
    if plan_id:
        manifest['plan_id'] = plan_id
    if plan_identifier:
        manifest['plan_identifier'] = plan_identifier
    return manifest


def write_manifest_file(manifest_path, manifest_data):
    manifest_path = Path(manifest_path)
    manifest_path.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=True),
        encoding='utf-8',
    )


def validate_local_storage_path(directory_path, create_if_missing=False):
    """Validate and optionally create a local storage directory."""
    raw_path = (directory_path or '').strip()
    if not raw_path:
        raise BackupError('Local storage path must not be empty.')
    if '..' in raw_path.replace('\\', '/').split('/'):
        raise BackupError('Local storage path must not contain parent references.')

    path = Path(raw_path)
    if not path.is_absolute():
        raise BackupError('Local storage path must be an absolute path.')

    path = path.resolve()
    if create_if_missing:
        path.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        raise BackupError('Local storage path does not exist: %s' % path)
    elif not path.is_dir():
        raise BackupError('Local storage path is not a directory: %s' % path)

    if not path.exists():
        raise BackupError('Local storage path could not be created: %s' % path)
    if not path.is_dir():
        raise BackupError('Local storage path is not a directory: %s' % path)

    test_file = path / '.cb_backup_write_test'
    try:
        test_file.write_text('ok', encoding='utf-8')
        test_file.unlink(missing_ok=True)
    except OSError as exc:
        raise BackupError('Local storage path is not writable: %s' % path) from exc

    return path


def create_backup_zip(source_dir, zip_path):
    """Create a ZIP archive from the contents of source_dir."""
    source_dir = Path(source_dir)
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(source_dir.rglob('*')):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(source_dir).as_posix())


def verify_backup_zip(zip_path):
    """Verify ZIP integrity and required members."""
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise BackupError('Backup ZIP file was not created.')

    with zipfile.ZipFile(zip_path, 'r') as archive:
        corrupt_file = archive.testzip()
        if corrupt_file:
            raise BackupError('Backup ZIP integrity check failed for: %s' % corrupt_file)

        names = set(archive.namelist())
        if MANIFEST_FILENAME not in names:
            raise BackupError('Backup ZIP is missing %s.' % MANIFEST_FILENAME)
        if not find_dump_member_name(names):
            raise BackupError(
                'Backup ZIP is missing %s (or legacy %s).'
                % (DATABASE_DUMP_FILENAME, LEGACY_DATABASE_DUMP_FILENAME)
            )


def compute_sha256(file_path):
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with Path(file_path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_error_message(message):
    """Remove sensitive fragments from error messages."""
    sanitized = (message or '').strip()
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub('[redacted]', sanitized)
    return sanitized or 'Unknown backup error.'


def format_bytes(num):
    """Return a short human-readable size for notifications."""
    value = float(num or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(value) < 1024.0 or unit == 'TB':
            if unit == 'B':
                return '%d B' % int(value)
            return '%.1f %s' % (value, unit)
        value /= 1024.0
    return '0 B'


def format_duration(seconds):
    """Return a short human-readable duration."""
    total = int(round(float(seconds or 0)))
    if total < 0:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return '%d h %d m' % (hours, minutes)
    if minutes:
        return '%d m %d s' % (minutes, secs)
    return '%d s' % secs


def classify_backup_outcome(destination_results):
    """Return success, partial, or failed from destination-level results."""
    results = list(destination_results or [])
    if not results:
        return 'failed'
    successes = [result for result in results if result.success]
    failures = [result for result in results if not result.success]
    if successes and not failures:
        return 'success'
    if successes and failures:
        return 'partial'
    return 'failed'


def format_destination_results(results):
    """Format destination-level results for history logging."""
    lines = []
    for result in results:
        line = '[%s] %s' % (result.status.upper(), result.destination)
        if result.final_path:
            line += ' -> %s' % result.final_path
        if result.error_message:
            line += ': %s' % result.error_message
        lines.append(line)
    return '\n'.join(lines)


def plan_directory_identifier(plan_id):
    """Return a filesystem-safe plan directory name. Never use the plan name."""
    return 'plan_%s' % int(plan_id)


def plan_relative_storage_dir(database_name, plan_id):
    """Return the plan-specific subdirectory under a storage root."""
    db_name = validate_database_name(database_name)
    return '%s/%s' % (db_name, plan_directory_identifier(plan_id))


def sanitize_relative_dir(relative_dir):
    """Reject absolute paths and parent-directory traversal."""
    raw = (relative_dir or '').strip().replace('\\', '/')
    if not raw:
        return ''
    rel = Path(raw)
    if rel.is_absolute() or any(part in ('.', '..') for part in rel.parts):
        raise BackupError('Invalid storage subdirectory.')
    return Path(*rel.parts).as_posix()


def normalize_sftp_root(remote_path):
    """Return a normalized absolute POSIX SFTP directory path."""
    raw = (remote_path or '').strip().replace('\\', '/')
    if not raw:
        raise BackupError('SFTP remote path must not be empty.')
    if not raw.startswith('/'):
        raise BackupError('SFTP remote path must be an absolute path.')
    parts = [part for part in raw.split('/') if part]
    if any(part in ('.', '..') for part in parts):
        raise BackupError('SFTP remote path must not contain parent references.')
    return '/' + '/'.join(parts) if parts else '/'


def join_sftp_path(root, *parts):
    """Join POSIX path parts under an SFTP root, rejecting traversal."""
    root_n = normalize_sftp_root(root)
    extra = sanitize_relative_dir('/'.join(str(part) for part in parts if part))
    if not extra:
        return root_n
    joined = '%s/%s' % (root_n.rstrip('/'), extra)
    if not is_sftp_path_inside(root_n, joined):
        raise BackupError('SFTP path is outside the configured remote directory.')
    return joined


def is_sftp_path_inside(root, target):
    """Return True if the POSIX target path is inside the SFTP root."""
    try:
        root_n = normalize_sftp_root(root)
    except BackupError:
        return False
    target_raw = (target or '').strip().replace('\\', '/')
    if not target_raw.startswith('/'):
        return False
    parts = [part for part in target_raw.split('/') if part]
    if any(part in ('.', '..') for part in parts):
        return False
    target_n = '/' + '/'.join(parts) if parts else '/'
    if target_n == root_n:
        return True
    prefix = root_n if root_n.endswith('/') else root_n + '/'
    return target_n.startswith(prefix)


def normalize_ssh_fingerprint(value):
    """Normalize an SSH fingerprint for comparison."""
    raw = (value or '').strip()
    if not raw:
        return ''
    if raw.lower().startswith('sha256:'):
        raw = raw.split(':', 1)[1]
    elif raw.lower().startswith('md5:'):
        raw = raw.split(':', 1)[1]
    return raw.replace(':', '').replace('=', '').replace(' ', '').lower()


def is_temporary_backup_filename(filename):
    name = Path(filename).name
    return (
        name.startswith('.')
        or name.endswith(PART_FILE_SUFFIX)
        or name.endswith(SFTP_UPLOAD_SUFFIX)
    )


def identify_managed_backup_from_fileobj(fileobj, filename, database_name, plan_id=None, require_plan_id=False):
    """Identify a managed backup ZIP or encrypted container from a seekable file object."""
    if is_temporary_backup_filename(filename):
        return False, None, 'Temporary or hidden file.'
    if not is_our_backup_filename(filename, database_name):
        return False, None, 'Filename does not match managed backup pattern.'
    from odoo.addons.cb_auto_backup_manager.models.backup_encryption import (
        identify_encrypted_backup_from_fileobj,
        is_encrypted_backup_fileobj,
    )
    if is_encrypted_backup_fileobj(fileobj):
        return identify_encrypted_backup_from_fileobj(
            fileobj, filename, database_name, plan_id=plan_id, require_plan_id=require_plan_id,
        )
    try:
        with zipfile.ZipFile(fileobj, 'r') as archive:
            if MANIFEST_FILENAME not in archive.namelist():
                return False, None, 'Missing or unreadable backup_manifest.json.'
            with archive.open(MANIFEST_FILENAME) as handle:
                manifest = json.loads(handle.read().decode('utf-8'))
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        return False, None, 'File is not a valid ZIP archive.'
    if not isinstance(manifest, dict):
        return False, None, 'Missing or unreadable backup_manifest.json.'
    return _match_backup_manifest(manifest, database_name, plan_id, require_plan_id)


def _match_backup_manifest(manifest, database_name, plan_id=None, require_plan_id=False):
    if manifest.get('module_name') != MODULE_NAME:
        return False, None, 'ZIP is not a CB Auto Backup Manager archive.'
    if manifest.get('database_name') != database_name:
        return False, None, 'ZIP belongs to a different database.'
    manifest_plan_id = manifest.get('plan_id')
    if require_plan_id and not manifest_plan_id:
        return False, manifest, 'ZIP has no plan identifier; skipped for safety.'
    if plan_id and manifest_plan_id and int(manifest_plan_id) != int(plan_id):
        return False, manifest, 'ZIP belongs to a different backup plan.'
    return True, manifest, ''


def is_path_inside(root, target):
    """Return True if target resolves inside root. Does not follow unsafe escapes."""
    try:
        root_resolved = Path(root).resolve()
        target_resolved = Path(target).resolve()
        target_resolved.relative_to(root_resolved)
        return True
    except (ValueError, OSError):
        return False


def is_our_backup_filename(filename, database_name=None):
    """Return True if filename matches <database>_YYYYMMDD_HHMMSS.zip or .enc."""
    match = _BACKUP_FILENAME_RE.match(Path(filename).name)
    if not match:
        return False
    if database_name and match.group(1) != database_name:
        return False
    return True


def parse_backup_filename_datetime(filename):
    """Parse the UTC timestamp encoded in a backup filename, or None."""
    match = _BACKUP_FILENAME_RE.match(Path(filename).name)
    if not match:
        return None
    try:
        return datetime.strptime('%s%s' % (match.group(2), match.group(3)), '%Y%m%d%H%M%S')
    except ValueError:
        return None


def calculate_retention_cutoff(now, retention_days):
    """
    Return cutoff datetime.

    Files with backup_datetime < cutoff are eligible for deletion.
    Files with backup_datetime >= cutoff are kept.

    Example: now=2026-08-12 23:00, retention_days=30
    cutoff=2026-07-13 23:00
    """
    if not retention_days or retention_days <= 0:
        raise BackupError('Retention days must be greater than zero.')
    return now - timedelta(days=retention_days)


def is_older_than_cutoff(backup_dt, cutoff_dt):
    """True when the backup is strictly older than the cutoff (KEEP at equality)."""
    if not backup_dt or not cutoff_dt:
        return False
    return backup_dt < cutoff_dt


def read_backup_manifest(zip_path):
    """Read backup_manifest.json from a ZIP without extracting the archive."""
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        return None
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            if MANIFEST_FILENAME not in archive.namelist():
                return None
            with archive.open(MANIFEST_FILENAME) as handle:
                data = json.loads(handle.read().decode('utf-8'))
            if not isinstance(data, dict):
                return None
            return data
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        return None


def identify_managed_backup(zip_path, database_name, plan_id=None, require_plan_id=False):
    """
    Confirm a ZIP is a CB Auto Backup Manager archive for this database/plan.

    Returns (identified, manifest_or_none, skip_reason).
    Uncertain files are skipped rather than deleted.
    """
    path = Path(zip_path)
    if path.is_symlink():
        return False, None, 'Skipped symlink.'
    if not path.is_file():
        return False, None, 'Not a file.'
    if is_temporary_backup_filename(path.name):
        return False, None, 'Temporary or hidden file.'
    if not is_our_backup_filename(path.name, database_name):
        return False, None, 'Filename does not match managed backup pattern.'
    from odoo.addons.cb_auto_backup_manager.models.backup_encryption import (
        identify_encrypted_backup,
        is_encrypted_backup_file,
    )
    if is_encrypted_backup_file(path) or path.suffix == '.enc':
        return identify_encrypted_backup(
            path, database_name, plan_id=plan_id, require_plan_id=require_plan_id,
        )
    if not zipfile.is_zipfile(path):
        return False, None, 'File is not a valid ZIP archive.'

    manifest = read_backup_manifest(path)
    if not manifest:
        return False, None, 'Missing or unreadable backup_manifest.json.'
    return _match_backup_manifest(manifest, database_name, plan_id, require_plan_id)


def backup_datetime_from_sources(manifest, filename, file_path=None):
    """Prefer manifest datetime, then filename timestamp, then filesystem mtime."""
    if manifest and manifest.get('backup_datetime'):
        raw = manifest['backup_datetime']
        try:
            parsed = datetime.fromisoformat(raw.replace('Z', ''))
            return parsed.replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
    from_name = parse_backup_filename_datetime(filename)
    if from_name:
        return from_name
    if file_path:
        try:
            return datetime.utcfromtimestamp(Path(file_path).stat().st_mtime)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def generate_temp_restore_database_name(source_database, backup_dt=None, suffix=None):
    """Build a PostgreSQL-safe temporary restore database name."""
    source = validate_database_name(source_database)
    stamp = (backup_dt or datetime.utcnow()).strftime('%Y%m%d_%H%M%S')
    extra = '_%s_%s' % (stamp, (suffix or uuid4().hex[:6]).lower())
    max_source = MAX_PG_IDENT_LENGTH - len(TEMP_RESTORE_DB_PREFIX) - len(extra)
    if max_source < 1:
        raise BackupError('Unable to generate a safe temporary database name.')
    name = '%s%s%s' % (TEMP_RESTORE_DB_PREFIX, source[:max_source], extra)
    return validate_database_name(name)


def is_temp_restore_database_name(database_name):
    """Return True if the name was generated by this module's restore test."""
    try:
        name = validate_database_name(database_name)
    except BackupError:
        return False
    return name.startswith(TEMP_RESTORE_DB_PREFIX) and len(name) <= MAX_PG_IDENT_LENGTH


def parse_odoo_major_version(version_string):
    """Return the leading major version integer from an Odoo version string."""
    match = re.search(r'(\d+)', version_string or '')
    if not match:
        return None
    return int(match.group(1))


def compare_odoo_versions(backup_version, current_version):
    """Return (compatible, major_mismatch, warning_message)."""
    backup = (backup_version or '').strip()
    current = (current_version or '').strip()
    if not backup:
        return True, False, ''
    backup_major = parse_odoo_major_version(backup)
    current_major = parse_odoo_major_version(current)
    if backup_major is None or current_major is None:
        return False, True, (
            'Restore compatibility warning: this backup was created from a '
            'different Odoo major version.'
        )
    if backup_major != current_major:
        return False, True, (
            'Restore compatibility warning: this backup was created from a '
            'different Odoo major version.'
        )
    if backup != current:
        return True, False, (
            'Backup was created with Odoo %s and the current server is Odoo %s.'
            % (backup, current)
        )
    return True, False, ''


def zip_member_is_symlink(info):
    """Return True if a ZipInfo looks like a Unix symbolic link."""
    mode = (getattr(info, 'external_attr', 0) or 0) >> 16
    return (mode & _ZIP_UNIX_IFMT) == _ZIP_UNIX_SYMLINK


def assert_safe_zip_member(member_name, dest_dir):
    """Reject ZIP members that would escape dest_dir."""
    raw = (member_name or '').replace('\\', '/')
    if not raw or '\x00' in raw:
        raise BackupError('ZIP contains an unsafe file name.')
    if raw.startswith('/') or re.match(r'^[a-zA-Z]:', raw):
        raise BackupError('ZIP contains an absolute path.')
    parts = [part for part in raw.split('/') if part and part != '.']
    if not parts:
        return
    if any(part == '..' for part in parts):
        raise BackupError('ZIP path traversal is not allowed.')
    dest = Path(dest_dir).resolve()
    target = dest.joinpath(*parts)
    if not is_path_inside(dest, target):
        raise BackupError('ZIP path traversal is not allowed.')


def extract_zip_safely(zip_path, dest_dir):
    """Extract a ZIP into dest_dir, rejecting traversal and symlinks."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(zip_path, 'r') as archive:
        for info in archive.infolist():
            name = (info.filename or '').replace('\\', '/')
            if not name or name.endswith('/'):
                continue
            if zip_member_is_symlink(info):
                raise BackupError('ZIP contains an unsafe symbolic link.')
            assert_safe_zip_member(name, dest_resolved)
            parts = [part for part in name.split('/') if part and part != '.']
            target = dest_resolved.joinpath(*parts)
            if not is_path_inside(dest_resolved, target):
                raise BackupError('ZIP path traversal is not allowed.')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, 'r') as source, target.open('wb') as handle:
                shutil.copyfileobj(source, handle, 1024 * 1024)
    return dest_resolved


def validate_restore_archive(zip_path, expected_checksum=None):
    """Run restore-time ZIP and structure checks. Returns the manifest dict."""
    path = Path(zip_path)
    if not path.exists():
        raise BackupError('Backup file does not exist.')
    if not path.is_file():
        raise BackupError('Backup path is not a readable file.')
    try:
        with path.open('rb') as handle:
            handle.read(1)
    except OSError as exc:
        raise BackupError('Backup file is not readable.') from exc
    if not zipfile.is_zipfile(path):
        raise BackupError('Backup file is not a valid ZIP archive.')

    with zipfile.ZipFile(path, 'r') as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise BackupError('Backup ZIP integrity check failed for: %s' % corrupt)
        names = [(name or '').replace('\\', '/') for name in archive.namelist()]
        for info in archive.infolist():
            if zip_member_is_symlink(info):
                raise BackupError('ZIP contains an unsafe symbolic link.')
            member = (info.filename or '').replace('\\', '/')
            if member and not member.endswith('/'):
                assert_safe_zip_member(member, path.parent / '_extract_check')
        if MANIFEST_FILENAME not in names:
            raise BackupError('Backup ZIP is missing %s.' % MANIFEST_FILENAME)
        if not find_dump_member_name(names):
            raise BackupError(
                'Backup ZIP is missing %s (or legacy %s).'
                % (DATABASE_DUMP_FILENAME, LEGACY_DATABASE_DUMP_FILENAME)
            )
        has_filestore = any(
            name == FILESTORE_DIRNAME or name.startswith(FILESTORE_DIRNAME + '/')
            for name in names
        )
        if not has_filestore:
            raise BackupError('Backup ZIP is missing the filestore directory.')

    if expected_checksum:
        actual = compute_sha256(path)
        if actual.lower() != expected_checksum.lower():
            raise BackupError(
                'Backup integrity verification failed. '
                'The backup file may be corrupted or modified.'
            )

    manifest = read_backup_manifest(path)
    if not manifest:
        raise BackupError('Backup ZIP is missing a readable %s.' % MANIFEST_FILENAME)
    validate_database_name(manifest.get('database_name'))
    return manifest


def find_dump_member_name(names):
    """Return dump.sql or legacy database.dump member name from a ZIP namelist."""
    normalized = {
        (name or '').replace('\\', '/').lstrip('/')
        for name in (names or [])
    }
    if DATABASE_DUMP_FILENAME in normalized:
        return DATABASE_DUMP_FILENAME
    if LEGACY_DATABASE_DUMP_FILENAME in normalized:
        return LEGACY_DATABASE_DUMP_FILENAME
    return ''


def resolve_dump_path(extract_dir):
    """Locate dump.sql or legacy database.dump under an extracted backup folder."""
    root = Path(extract_dir)
    preferred = root / DATABASE_DUMP_FILENAME
    if preferred.is_file():
        return preferred
    legacy = root / LEGACY_DATABASE_DUMP_FILENAME
    if legacy.is_file():
        return legacy
    raise BackupError(
        'Extracted backup is missing %s (or legacy %s).'
        % (DATABASE_DUMP_FILENAME, LEGACY_DATABASE_DUMP_FILENAME)
    )


def detect_dump_format(dump_path):
    """Return 'custom' or 'plain' from a PostgreSQL dump header."""
    path = Path(dump_path)
    with path.open('rb') as handle:
        header = handle.read(5)
    if header.startswith(b'PGDMP'):
        return 'custom'
    return 'plain'
