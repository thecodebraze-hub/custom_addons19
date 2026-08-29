# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    MANIFEST_FILENAME,
    BackupError,
    create_backup_zip,
    write_manifest_file,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)


@tagged('post_install', '-at_install')
class TestBackupStorageProviders(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']

    def _create_local_storage(self, path):
        return self.Storage.create({
            'name': 'Local Test Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _create_zip(self, temp_dir):
        workspace = Path(temp_dir) / 'workspace'
        workspace.mkdir()
        (workspace / DATABASE_DUMP_FILENAME).write_bytes(b'pg-dump-content')
        write_manifest_file(workspace / MANIFEST_FILENAME, {'database_name': 'odoo19'})
        zip_path = Path(temp_dir) / 'odoo19_20260811_120000.zip'
        create_backup_zip(workspace, zip_path)
        return zip_path

    def test_local_storage_success(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as dest_dir:
            storage = self._create_local_storage(dest_dir)
            provider = get_storage_provider(storage)
            zip_path = self._create_zip(source_dir)
            result = provider.store(str(zip_path), zip_path.name)
            self.assertTrue(result.success)
            self.assertTrue(Path(result.final_path).is_file())

    def test_invalid_local_storage(self):
        storage = self._create_local_storage('relative/path')
        provider = get_storage_provider(storage)
        with self.assertRaises(BackupError):
            provider.validate()

    def test_sftp_provider_is_selected(self):
        storage = self.Storage.create({
            'name': 'SFTP Selected %s' % uuid4().hex[:8],
            'type': 'sftp',
            'sftp_host': 'backup.example.com',
            'sftp_username': 'user',
            'sftp_password': 'secret',
            'sftp_remote_path': '/backups/odoo',
        })
        provider = get_storage_provider(storage)
        self.assertEqual(provider.provider_type, 'sftp')
        provider.validate(connect=False)

    def test_google_drive_requires_authorization(self):
        storage = self.Storage.create({
            'name': 'Google Drive Future %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_account': 'backup@example.com',
            'google_drive_folder': 'Odoo Backups',
            'google_drive_client_id': 'client.apps.googleusercontent.com',
            'google_drive_client_secret': 'test-client-secret',
        })
        provider = get_storage_provider(storage)
        with tempfile.NamedTemporaryFile(suffix='.zip') as handle:
            result = provider.store(handle.name, 'test.zip')
        self.assertFalse(result.success)
        self.assertEqual(result.status, 'failed')
        self.assertIn('not authorized', result.error_message)

    def test_reuse_same_zip_for_multiple_destinations(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as dest_a, tempfile.TemporaryDirectory() as dest_b:
            storage_a = self._create_local_storage(dest_a)
            storage_b = self._create_local_storage(dest_b)
            zip_path = self._create_zip(source_dir)
            result_a = get_storage_provider(storage_a).store(str(zip_path), zip_path.name)
            result_b = get_storage_provider(storage_b).store(str(zip_path), zip_path.name)
            self.assertTrue(result_a.success)
            self.assertTrue(result_b.success)

    def test_validate_storage_action_local(self):
        with tempfile.TemporaryDirectory() as dest_dir:
            storage = self._create_local_storage(dest_dir)
            action = storage.action_validate_storage()
            self.assertEqual(action['tag'], 'display_notification')
            self.assertEqual(storage.validation_status, 'valid')

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump')
    def test_unsupported_destination_marks_history_failed(self, mock_run_pg_dump):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        mock_run_pg_dump.side_effect = _fake_dump
        filestore = Path(tempfile.mkdtemp()) / 'filestore' / self.env.cr.dbname
        filestore.mkdir(parents=True, exist_ok=True)
        (filestore / 'attachment.bin').write_bytes(b'x')

        with tempfile.TemporaryDirectory() as local_dir:
            local_storage = self._create_local_storage(local_dir)
            gdrive_storage = self.Storage.create({
                'name': 'Google Drive Future 2 %s' % uuid4().hex[:8],
                'type': 'google_drive',
                'google_drive_account': 'backup@example.com',
                'google_drive_folder': 'Odoo Backups',
            })
            plan = self.env['cb.backup.plan'].create({
                'name': 'Multi Destination Plan %s' % uuid4().hex[:8],
                'database_name': self.env.cr.dbname,
                'timezone': 'UTC',
                'state': 'active',
                'storage_destination_ids': [(6, 0, [local_storage.id, gdrive_storage.id])],
                'schedule_ids': [(0, 0, {
                    'frequency': 'daily',
                    'time_hour': 1,
                    'time_minute': 0,
                })],
            })

            with patch.object(
                type(self.env['cb.backup.service']),
                'get_filestore_path',
                return_value=filestore,
            ):
                self.env['cb.backup.service'].execute_plan_backup(plan, trigger='manual')

            history = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ], limit=1)
            self.assertEqual(history.status, 'partial')
            statuses = set(history.destination_result_ids.mapped('status'))
            self.assertIn('success', statuses)
            self.assertIn('failed', statuses)
