# -*- coding: utf-8 -*-
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    LEGACY_DATABASE_DUMP_FILENAME,
    MANIFEST_FILENAME,
    BackupError,
    build_backup_manifest,
    calculate_retention_cutoff,
    classify_backup_outcome,
    compute_sha256,
    create_backup_zip,
    extract_zip_safely,
    find_dump_member_name,
    format_bytes,
    format_duration,
    generate_backup_filename,
    generate_temp_restore_database_name,
    is_older_than_cutoff,
    is_our_backup_filename,
    is_path_inside,
    is_sftp_path_inside,
    is_temp_restore_database_name,
    join_sftp_path,
    normalize_sftp_root,
    plan_relative_storage_dir,
    resolve_dump_path,
    sanitize_error_message,
    sanitize_relative_dir,
    validate_database_name,
    validate_local_storage_path,
    validate_restore_archive,
    verify_backup_zip,
    write_manifest_file,
)


@tagged('post_install', '-at_install')
class TestBackupUtils(TransactionCase):

    def test_temp_restore_database_name_and_zip_safety(self):
        name = generate_temp_restore_database_name('company_live', datetime(2026, 8, 13, 23, 0, 0), 'abc123')
        self.assertTrue(name.startswith('backup_test_'))
        self.assertTrue(is_temp_restore_database_name(name))
        self.assertFalse(is_temp_restore_database_name('odoo19'))
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / 'evil.zip'
            with zipfile.ZipFile(zip_path, 'w') as archive:
                archive.writestr('/tmp/abs.txt', b'nope')
            extract_dir = Path(temp_dir) / 'out'
            extract_dir.mkdir()
            with self.assertRaises(BackupError):
                extract_zip_safely(zip_path, extract_dir)

    def test_format_duration_and_bytes(self):
        self.assertEqual(format_duration(12), '12 s')
        self.assertEqual(format_duration(75), '1 m 15 s')
        self.assertEqual(format_duration(3661), '1 h 1 m')
        self.assertEqual(format_bytes(1024), '1.0 KB')

    def test_validate_database_name(self):
        self.assertEqual(validate_database_name('odoo19'), 'odoo19')
        with self.assertRaises(BackupError):
            validate_database_name('')
        with self.assertRaises(BackupError):
            validate_database_name('bad-name')

    def test_generate_backup_filename(self):
        backup_dt = datetime(2026, 8, 11, 23, 45, 0)
        filename = generate_backup_filename('odoo19', backup_dt)
        self.assertEqual(filename, 'odoo19_20260811_234500.zip')
        enc_name = generate_backup_filename('odoo19', backup_dt, encrypted=True)
        self.assertEqual(enc_name, 'odoo19_20260811_234500.enc')

    def test_manifest_generation(self):
        manifest = build_backup_manifest(
            database_name='odoo19',
            backup_datetime=datetime(2026, 8, 11, 23, 45, 0),
            odoo_version='19.0',
            module_version='19.0.2.0.0',
            filestore_included=True,
        )
        self.assertEqual(manifest['database_name'], 'odoo19')
        self.assertEqual(manifest['database_dump_filename'], 'dump.sql')
        self.assertEqual(DATABASE_DUMP_FILENAME, 'dump.sql')
        self.assertNotIn('password', manifest)
        self.assertNotIn('secret', manifest)
        self.assertEqual(manifest['encryption_method'], 'none')

    def test_dump_sql_and_legacy_database_dump_resolution(self):
        self.assertEqual(find_dump_member_name(['dump.sql', 'filestore/a']), 'dump.sql')
        self.assertEqual(
            find_dump_member_name(['database.dump', 'backup_manifest.json']),
            LEGACY_DATABASE_DUMP_FILENAME,
        )
        self.assertEqual(find_dump_member_name(['filestore/a']), '')
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / LEGACY_DATABASE_DUMP_FILENAME).write_bytes(b'PGDMP')
            self.assertEqual(resolve_dump_path(root).name, LEGACY_DATABASE_DUMP_FILENAME)
            (root / DATABASE_DUMP_FILENAME).write_bytes(b'-- sql')
            self.assertEqual(resolve_dump_path(root).name, DATABASE_DUMP_FILENAME)
    def test_local_storage_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            validated = validate_local_storage_path(temp_dir, create_if_missing=True)
            self.assertTrue(validated.is_dir())

    def test_invalid_local_storage(self):
        with self.assertRaises(BackupError):
            validate_local_storage_path('relative/path')

    def test_zip_integrity_and_checksum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / 'workspace'
            workspace.mkdir()
            (workspace / DATABASE_DUMP_FILENAME).write_bytes(b'dump-data')
            write_manifest_file(
                workspace / MANIFEST_FILENAME,
                {'database_name': 'odoo19'},
            )
            zip_path = Path(temp_dir) / 'backup.zip'
            create_backup_zip(workspace, zip_path)
            verify_backup_zip(zip_path)
            checksum = compute_sha256(zip_path)
            self.assertEqual(len(checksum), 64)

    def test_sanitize_error_message(self):
        message = sanitize_error_message('password=secret PGPASSWORD=abc')
        self.assertNotIn('secret', message)
        self.assertIn('[redacted]', message)
        key_message = sanitize_error_message(
            'auth failed -----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----'
        )
        self.assertNotIn('BEGIN OPENSSH PRIVATE KEY', key_message)
        token_message = sanitize_error_message('refresh_token=abc123 access_token=zzz')
        self.assertNotIn('abc123', token_message)
        self.assertNotIn('zzz', token_message)

    def test_format_bytes_and_outcome(self):
        self.assertEqual(format_bytes(0), '0 B')
        self.assertIn('GB', format_bytes(1.8 * 1024 * 1024 * 1024))
        from odoo.addons.cb_auto_backup_manager.services.storage_providers.base import StorageResult
        success = StorageResult(True, 'Local', status='success')
        failed = StorageResult(False, 'SFTP', status='failed')
        self.assertEqual(classify_backup_outcome([success, success]), 'success')
        self.assertEqual(classify_backup_outcome([success, failed]), 'partial')
        self.assertEqual(classify_backup_outcome([failed]), 'failed')

    def test_sftp_path_helpers(self):
        self.assertEqual(normalize_sftp_root('/backups/odoo/'), '/backups/odoo')
        self.assertTrue(is_sftp_path_inside('/backups/odoo', '/backups/odoo/db/plan_1/a.zip'))
        self.assertFalse(is_sftp_path_inside('/backups/odoo', '/backups/odoo_other/a.zip'))
        self.assertEqual(
            join_sftp_path('/backups/odoo', 'db', 'plan_1'),
            '/backups/odoo/db/plan_1',
        )
        with self.assertRaises(BackupError):
            normalize_sftp_root('relative')
        with self.assertRaises(BackupError):
            join_sftp_path('/backups/odoo', '..', 'etc')

    def test_retention_cutoff_boundary(self):
        now = datetime(2026, 8, 12, 23, 0, 0)
        cutoff = calculate_retention_cutoff(now, 30)
        self.assertEqual(cutoff, datetime(2026, 7, 13, 23, 0, 0))
        self.assertTrue(is_older_than_cutoff(datetime(2026, 7, 12, 23, 0, 0), cutoff))
        self.assertTrue(is_older_than_cutoff(datetime(2026, 7, 13, 22, 59, 0), cutoff))
        self.assertFalse(is_older_than_cutoff(datetime(2026, 7, 13, 23, 0, 0), cutoff))
        self.assertFalse(is_older_than_cutoff(datetime(2026, 7, 14, 0, 0, 0), cutoff))
        with self.assertRaises(BackupError):
            calculate_retention_cutoff(now, 0)
        for days in (7, 30, 60, 90, 365):
            window = calculate_retention_cutoff(now, days)
            self.assertEqual(window, now - timedelta(days=days))
            self.assertTrue(is_older_than_cutoff(window - timedelta(seconds=1), window))
            self.assertFalse(is_older_than_cutoff(window, window))

    def test_backup_filename_and_plan_dir(self):
        self.assertTrue(is_our_backup_filename('odoo19_20260811_234500.zip', 'odoo19'))
        self.assertTrue(is_our_backup_filename('odoo19_20260811_234500.enc', 'odoo19'))
        self.assertFalse(is_our_backup_filename('notes.txt', 'odoo19'))
        self.assertFalse(is_our_backup_filename('otherdb_20260811_234500.zip', 'odoo19'))
        self.assertEqual(plan_relative_storage_dir('odoo19', 12), 'odoo19/plan_12')
        with self.assertRaises(BackupError):
            sanitize_relative_dir('../etc')

    def test_path_inside_protection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inside = root / 'odoo19' / 'plan_1' / 'file.zip'
            inside.parent.mkdir(parents=True)
            inside.write_bytes(b'x')
            self.assertTrue(is_path_inside(root, inside))
            self.assertFalse(is_path_inside(root, root.parent / 'outside.zip'))
