# -*- coding: utf-8 -*-
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import odoo.release
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    FILESTORE_DIRNAME,
    MANIFEST_FILENAME,
    BackupError,
    build_backup_manifest,
    compute_sha256,
    create_backup_zip,
    extract_zip_safely,
    generate_temp_restore_database_name,
    is_temp_restore_database_name,
    validate_database_name,
    validate_restore_archive,
    write_manifest_file,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.sftp import (
    SftpStorageProvider,
)
from odoo.addons.cb_auto_backup_manager.tests.test_backup_sftp import FakeSFTP, FakeSSH


@tagged('post_install', '-at_install')
class TestBackupRestore(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.History = cls.env['cb.backup.history']
        cls.Restore = cls.env['cb.backup.restore.service']
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')
        cls.admin_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_administrator')

    def _operator(self):
        return self.env['res.users'].create({
            'name': 'Restore Operator',
            'login': 'cb_restore_op_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.operator_group.id,
            ])],
        })

    def _admin_user(self):
        return self.env['res.users'].create({
            'name': 'Restore Admin',
            'login': 'cb_restore_admin_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.admin_group.id,
            ])],
        })

    def _create_local_storage(self, path):
        return self.Storage.create({
            'name': 'Restore Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _create_plan(self, storage):
        plan = self.Plan.create({
            'name': 'Restore Plan %s' % uuid4().hex[:8],
            'database_name': self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'storage_destination_ids': [(6, 0, [storage.id])],
            'schedule_ids': [(0, 0, {
                'frequency': 'daily',
                'time_hour': 23,
                'time_minute': 0,
            })],
        })
        plan.action_activate()
        return plan

    def _make_backup_zip(self, directory, database_name=None, odoo_version=None, with_filestore=True,
                         with_manifest=True, with_dump=True, dump_bytes=None):
        directory = Path(directory)
        workspace = directory / ('.ws_%s' % uuid4().hex[:6])
        workspace.mkdir(parents=True)
        db_name = database_name or self.env.cr.dbname
        odoo_version = odoo_version if odoo_version is not None else odoo.release.version
        if with_dump:
            (workspace / DATABASE_DUMP_FILENAME).write_bytes(dump_bytes or b'PGDMP\x00fake-dump')
        if with_filestore:
            filestore = workspace / FILESTORE_DIRNAME
            filestore.mkdir()
            (filestore / 'attachment.bin').write_bytes(b'attachment')
        if with_manifest:
            write_manifest_file(
                workspace / MANIFEST_FILENAME,
                build_backup_manifest(
                    database_name=db_name,
                    backup_datetime=datetime(2026, 8, 13, 23, 0, 0),
                    odoo_version=odoo_version,
                    module_version='19.0.8.0.0',
                    filestore_included=True,
                ),
            )
        zip_path = directory / ('%s_20260813_230000.zip' % db_name)
        create_backup_zip(workspace, zip_path)
        return zip_path

    def _create_history(self, plan, storage, zip_path, **kwargs):
        checksum = compute_sha256(zip_path) if zip_path and Path(zip_path).is_file() else False
        vals = {
            'plan_id': plan.id,
            'database_name': plan.database_name,
            'backup_datetime': fields.Datetime.now(),
            'file_name': Path(zip_path).name if zip_path else 'missing.zip',
            'file_path': str(zip_path) if zip_path else False,
            'file_size': Path(zip_path).stat().st_size if zip_path and Path(zip_path).is_file() else 0,
            'checksum': checksum,
            'status': 'success',
            'destination_result_ids': [(0, 0, {
                'storage_id': storage.id,
                'storage_name': storage.name,
                'storage_type': storage.type,
                'status': 'success',
                'file_path': str(zip_path) if zip_path else False,
                'file_size': Path(zip_path).stat().st_size if zip_path and Path(zip_path).is_file() else 0,
            })],
        }
        vals.update(kwargs)
        return self.History.create(vals)

    def test_valid_backup_verification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir)
            history = self._create_history(plan, storage, zip_path)
            result = self.Restore.verify_backup(history, storage=storage)
            self.assertTrue(result['success'])
            self.assertEqual(result['message'], 'Backup verification successful.')
            self.assertTrue(result['checksum_verified'])
            self.assertTrue(result['filestore_verified'])
            self.assertEqual(history.verification_status, 'verified')
            self.assertTrue(history.restore_log_ids)

    def test_missing_zip(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            missing = Path(local_dir) / ('%s_20260813_230000.zip' % plan.database_name)
            history = self._create_history(plan, storage, missing)
            result = self.Restore.verify_backup(history, storage=storage)
            self.assertFalse(result['success'])
            self.assertEqual(result['message'], 'Backup verification failed.')

    def test_corrupted_zip(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = Path(local_dir) / ('%s_20260813_230000.zip' % plan.database_name)
            zip_path.write_bytes(b'not-a-zip')
            history = self._create_history(plan, storage, zip_path)
            result = self.Restore.verify_backup(history, storage=storage)
            self.assertFalse(result['success'])

    def test_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir)
            history = self._create_history(plan, storage, zip_path, checksum='0' * 64)
            result = self.Restore.verify_backup(history, storage=storage)
            self.assertFalse(result['success'])
            self.assertIn('corrupted or modified', result['error_message'])

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir, with_manifest=False)
            history = self._create_history(plan, storage, zip_path, checksum=False)
            result = self.Restore.verify_backup(history, storage=storage)
            self.assertFalse(result['success'])
            self.assertIn('backup_manifest.json', result['error_message'])

    def test_missing_database_dump(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir, with_dump=False)
            history = self._create_history(plan, storage, zip_path, checksum=False)
            result = self.Restore.verify_backup(history, storage=storage)
            self.assertFalse(result['success'])
            self.assertIn('dump.sql', result['error_message'])

    def test_missing_filestore(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir, with_filestore=False)
            history = self._create_history(plan, storage, zip_path, checksum=False)
            result = self.Restore.verify_backup(history, storage=storage)
            self.assertFalse(result['success'])
            self.assertIn('filestore', result['error_message'])

    def test_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / 'evil.zip'
            with zipfile.ZipFile(zip_path, 'w') as archive:
                archive.writestr('../evil.txt', b'nope')
                archive.writestr(MANIFEST_FILENAME, b'{"database_name": "odoo19"}')
                archive.writestr(DATABASE_DUMP_FILENAME, b'PGDMP')
                archive.writestr('filestore/a.bin', b'x')
            extract_dir = Path(temp_dir) / 'out'
            extract_dir.mkdir()
            with self.assertRaises(BackupError):
                extract_zip_safely(zip_path, extract_dir)
            self.assertFalse((Path(temp_dir) / 'evil.txt').exists())

    def test_invalid_database_name(self):
        with self.assertRaises(BackupError):
            validate_database_name("'; DROP DATABASE odoo19; --")
        with self.assertRaises(BackupError):
            generate_temp_restore_database_name('bad-name')
        name = generate_temp_restore_database_name(self.env.cr.dbname)
        self.assertTrue(is_temp_restore_database_name(name))
        self.assertTrue(name.startswith('backup_test_'))

    def test_temporary_database_creation_and_cleanup(self):
        name = generate_temp_restore_database_name('restoreunit')
        self.Restore._create_empty_database(name)
        self.assertTrue(self.Restore._pg_database_exists(name))
        log = self.env['cb.backup.restore.log'].create({
            'restore_mode': 'temporary_restore',
            'target_database': name,
            'created_database': True,
            'status': 'running',
        })
        self.Restore._drop_temp_database(name, log)
        self.assertFalse(self.Restore._pg_database_exists(name))

    def test_temporary_database_restore(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir)
            history = self._create_history(plan, storage, zip_path)
            with patch.object(type(self.Restore), '_restore_dump'), patch.object(
                type(self.Restore), '_validate_temp_database'
            ):
                result = self.Restore.test_restore(history, storage=storage, cleanup_after_test=True)
            self.assertTrue(result['success'])
            self.assertIn('temporary database', result['message'])
            self.assertEqual(history.restore_test_status, 'success')
            log = result['log']
            self.assertTrue(log.target_database)
            self.assertFalse(self.Restore._pg_database_exists(log.target_database))
            self.assertEqual(log.cleanup_status, 'cleaned')

    def test_odoo_table_and_filestore_validation(self):
        with tempfile.TemporaryDirectory() as local_dir:
            zip_path = self._make_backup_zip(local_dir)
            extract_dir = Path(local_dir) / 'extracted'
            extract_zip_safely(zip_path, extract_dir)
            self.Restore._validate_extracted_filestore(extract_dir / FILESTORE_DIRNAME)
            manifest = validate_restore_archive(zip_path, expected_checksum=compute_sha256(zip_path))
            self.assertEqual(manifest['database_name'], self.env.cr.dbname)

    def test_current_database_protection(self):
        with self.assertRaises(BackupError):
            self.Restore._assert_not_live_or_protected(self.env.cr.dbname, destructive=True)
        with self.assertRaises(BackupError):
            self.Restore._create_empty_database(self.env.cr.dbname)
        log = self.env['cb.backup.restore.log'].create({
            'restore_mode': 'temporary_restore',
            'target_database': self.env.cr.dbname,
            'created_database': True,
            'status': 'running',
        })
        with self.assertRaises(BackupError):
            self.Restore._drop_temp_database(self.env.cr.dbname, log)
        self.assertTrue(self.Restore._pg_database_exists(self.env.cr.dbname))

    def test_configured_production_database_protection(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            with self.assertRaises(BackupError):
                self.Restore._assert_not_live_or_protected(plan.database_name, destructive=True)
            with self.assertRaises(BackupError):
                self.Restore._assert_not_live_or_protected('postgres', destructive=True)

    def test_restore_log_creation(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir)
            history = self._create_history(plan, storage, zip_path)
            before = self.env['cb.backup.restore.log'].search_count([])
            self.Restore.verify_backup(history, storage=storage)
            self.assertGreater(self.env['cb.backup.restore.log'].search_count([]), before)

    def test_version_mismatch_warning(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir, odoo_version='18.0')
            history = self._create_history(plan, storage, zip_path)
            verify = self.Restore.verify_backup(history, storage=storage)
            self.assertTrue(verify['success'])
            self.assertEqual(verify['status'], 'warning')
            with patch.object(type(self.Restore), '_restore_dump'), patch.object(
                type(self.Restore), '_validate_temp_database'
            ):
                blocked = self.Restore.test_restore(
                    history, storage=storage, acknowledge_version_warning=False,
                )
            self.assertFalse(blocked['success'])
            self.assertIn('different Odoo major version', blocked['error_message'])
            with patch.object(type(self.Restore), '_restore_dump'), patch.object(
                type(self.Restore), '_validate_temp_database'
            ):
                allowed = self.Restore.test_restore(
                    history, storage=storage, acknowledge_version_warning=True,
                )
            self.assertTrue(allowed['success'])

    def test_sftp_download_provider_integration(self):
        with tempfile.TemporaryDirectory() as sandbox:
            storage = self.Storage.create({
                'name': 'Restore SFTP %s' % uuid4().hex[:8],
                'type': 'sftp',
                'sftp_host': 'backup.example.com',
                'sftp_port': 22,
                'sftp_username': 'backupuser',
                'sftp_authentication_type': 'password',
                'sftp_password': 'secret-password',
                'sftp_remote_path': '/backups/odoo',
                'sftp_host_key': 'SHA256:configuredfingerprint',
            })
            remote_dir = Path(sandbox) / 'backups' / 'odoo'
            remote_dir.mkdir(parents=True)
            zip_path = self._make_backup_zip(remote_dir)
            local_copy = Path(sandbox) / 'downloaded.zip'
            fake = FakeSFTP(sandbox)
            ssh = FakeSSH()
            with patch.object(SftpStorageProvider, '_require_paramiko', return_value=None), patch.object(
                SftpStorageProvider, '_open_session', return_value=(ssh, fake),
            ):
                result = get_storage_provider(storage).download_backup(
                    '/backups/odoo/%s' % zip_path.name,
                    local_copy,
                )
            self.assertTrue(result.success)
            self.assertTrue(local_copy.is_file())
            self.assertEqual(local_copy.stat().st_size, zip_path.stat().st_size)

    def test_google_drive_download_provider_integration(self):
        storage = self.Storage.create({
            'name': 'Restore GDrive %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_folder': 'Backups',
            'google_drive_client_id': 'client.apps.googleusercontent.com',
            'google_drive_client_secret': 'test-client-secret',
        })
        result = get_storage_provider(storage).download_backup('gdrive:notauthorizedfileidxxx', '/tmp/out.zip')
        self.assertFalse(result.success)
        self.assertEqual(result.status, 'failed')
        self.assertIn('not authorized', result.error_message)

    def test_notification_behavior(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir)
            history = self._create_history(plan, storage, zip_path)
            wizard = self.env['cb.backup.restore.wizard'].with_context(
                default_history_id=history.id,
            ).create({})
            action = wizard.action_verify()
            self.assertEqual(action['tag'], 'display_notification')
            self.assertIn('successful', action['params']['message'])
            self.assertEqual(action['params']['type'], 'success')

    def test_permission_restrictions(self):
        operator = self._operator()
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_backup_zip(local_dir)
            history = self._create_history(plan, storage, zip_path)
            result = self.Restore.with_user(operator).verify_backup(history, storage=storage)
            self.assertTrue(result['success'])
            with self.assertRaises(UserError):
                self.Restore.with_user(operator).test_restore(history, storage=storage)
            with self.assertRaises(UserError):
                history.with_user(operator).action_test_restore()

    def test_dashboard_restore_status(self):
        dash = self.env['cb.backup.dashboard'].create({})
        self.assertEqual(dash.last_verification_status, 'Never Tested')
        self.assertEqual(dash.last_restore_test_status, 'Never Tested')

    def test_single_scheduler_cron(self):
        crons = self.env['ir.cron'].search([('model_id.model', '=', 'cb.backup.plan')])
        self.assertEqual(len(crons), 1)
