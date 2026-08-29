# -*- coding: utf-8 -*-
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    MANIFEST_FILENAME,
    build_backup_manifest,
    create_backup_zip,
    generate_backup_filename,
    write_manifest_file,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)


@tagged('post_install', '-at_install')
class TestBackupCleanup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.Cleanup = cls.env['cb.backup.cleanup.service']
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')

    def _create_local_storage(self, path):
        return self.Storage.create({
            'name': 'Cleanup Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _create_active_plan(self, storage, retention_days=30, dbname=None):
        plan = self.Plan.create({
            'name': 'Cleanup Plan %s' % uuid4().hex[:8],
            'database_name': dbname or self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'retention_days': retention_days,
            'storage_destination_ids': [(6, 0, [storage.id])],
            'schedule_ids': [(0, 0, {
                'frequency': 'daily',
                'time_hour': 6,
                'time_minute': 0,
            })],
        })
        plan.action_activate()
        return plan

    def _write_managed_zip(self, directory, database_name, plan_id, backup_dt):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        workspace = directory / ('.ws_%s' % uuid4().hex[:6])
        workspace.mkdir()
        (workspace / DATABASE_DUMP_FILENAME).write_bytes(b'dump')
        write_manifest_file(
            workspace / MANIFEST_FILENAME,
            build_backup_manifest(
                database_name=database_name,
                backup_datetime=backup_dt,
                odoo_version='19.0',
                module_version='19.0.3.0.0',
                filestore_included=True,
                plan_id=plan_id,
                plan_identifier='plan_%s' % plan_id,
            ),
        )
        filename = generate_backup_filename(database_name, backup_dt)
        zip_path = directory / filename
        create_backup_zip(workspace, zip_path)
        for child in workspace.iterdir():
            child.unlink()
        workspace.rmdir()
        return zip_path

    def test_retention_days_validation(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            with self.assertRaises(ValidationError):
                self.Plan.create({
                    'name': 'Bad Retention %s' % uuid4().hex[:8],
                    'database_name': self.env.cr.dbname,
                    'timezone': 'UTC',
                    'retention_days': 0,
                    'storage_destination_ids': [(6, 0, [storage.id])],
                })

    def test_old_backup_deleted_recent_kept(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=30)
            plan_dir = Path(local_dir) / plan.get_storage_relative_dir()
            now = datetime(2026, 8, 12, 23, 0, 0)
            old_zip = self._write_managed_zip(
                plan_dir, plan.database_name, plan.id, datetime(2026, 7, 12, 23, 0, 0),
            )
            boundary_zip = self._write_managed_zip(
                plan_dir, plan.database_name, plan.id, datetime(2026, 7, 13, 23, 0, 0),
            )
            recent_zip = self._write_managed_zip(
                plan_dir, plan.database_name, plan.id, datetime(2026, 7, 14, 0, 0, 0),
            )
            with patch('odoo.addons.cb_auto_backup_manager.models.backup_cleanup_service.fields.Datetime.now', return_value=now):
                logs = self.Cleanup.cleanup_plan(plan, trigger='manual')
            self.assertFalse(old_zip.exists())
            self.assertTrue(boundary_zip.exists())
            self.assertTrue(recent_zip.exists())
            self.assertEqual(sum(logs.mapped('files_deleted')), 1)

    def test_unrelated_and_other_database_files_preserved(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            plan_dir = Path(local_dir) / plan.get_storage_relative_dir()
            plan_dir.mkdir(parents=True)
            notes = plan_dir / 'readme.txt'
            notes.write_text('keep me')
            other_zip = self._write_managed_zip(
                plan_dir, 'otherdb', plan.id, datetime(2020, 1, 1, 0, 0, 0),
            )
            logs = self.Cleanup.cleanup_plan(plan, trigger='manual')
            self.assertTrue(notes.exists())
            self.assertTrue(other_zip.exists())
            self.assertGreaterEqual(sum(logs.mapped('files_skipped')), 1)

    def test_other_plan_backups_preserved(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan_a = self._create_active_plan(storage, retention_days=1)
            plan_b = self._create_active_plan(storage, retention_days=365)
            old_a = self._write_managed_zip(
                Path(local_dir) / plan_a.get_storage_relative_dir(),
                plan_a.database_name,
                plan_a.id,
                datetime(2020, 1, 1, 12, 0, 0),
            )
            old_b = self._write_managed_zip(
                Path(local_dir) / plan_b.get_storage_relative_dir(),
                plan_b.database_name,
                plan_b.id,
                datetime(2020, 1, 1, 12, 0, 0),
            )
            self.Cleanup.cleanup_plan(plan_a, trigger='manual')
            self.assertFalse(old_a.exists())
            self.assertTrue(old_b.exists())

    def test_path_traversal_and_symlink_safety(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            provider = get_storage_provider(storage)
            outside = Path(tempfile.gettempdir()) / ('cb_outside_%s.zip' % uuid4().hex[:6])
            outside.write_bytes(b'not-a-backup')
            result = provider.delete_backup(str(outside))
            self.assertFalse(result.success)
            self.assertIn('outside', (result.error_message or '').lower())
            outside.unlink(missing_ok=True)

            plan_dir = Path(local_dir) / plan.get_storage_relative_dir()
            plan_dir.mkdir(parents=True)
            target = plan_dir / 'target.txt'
            target.write_text('secret')
            link = plan_dir / 'link.zip'
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                return
            listed = provider.list_backups(
                relative_dir=plan.get_storage_relative_dir(),
                database_name=plan.database_name,
                plan_id=plan.id,
            )
            self.assertTrue(any('symlink' in (item.skip_reason or '').lower() for item in listed.files) or not listed.files)
            delete_result = provider.delete_backup(str(link))
            self.assertFalse(delete_result.success)
            self.assertTrue(target.exists())

    def test_failed_file_deletion_is_partial(self):
        from odoo.addons.cb_auto_backup_manager.services.storage_providers.base import StorageResult

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            zip_path = self._write_managed_zip(
                Path(local_dir) / plan.get_storage_relative_dir(),
                plan.database_name,
                plan.id,
                datetime(2020, 1, 1, 12, 0, 0),
            )
            provider = get_storage_provider(storage)
            failed = StorageResult(
                success=False,
                destination=storage.name,
                status='failed',
                error_message='Permission denied',
                metadata={'storage_id': storage.id},
            )
            with patch.object(type(provider), 'delete_backup', return_value=failed), patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_cleanup_service.get_storage_provider',
                return_value=provider,
            ):
                logs = self.Cleanup.cleanup_plan(plan, trigger='manual')
            self.assertTrue(zip_path.exists())
            self.assertIn(logs.status, ('partial', 'failed'))

    def test_successful_deletion_creates_log_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            zip_path = self._write_managed_zip(
                Path(local_dir) / plan.get_storage_relative_dir(),
                plan.database_name,
                plan.id,
                datetime(2020, 1, 1, 12, 0, 0),
            )
            history = self.env['cb.backup.history'].create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'backup_datetime': datetime(2020, 1, 1, 12, 0, 0),
                'file_name': zip_path.name,
                'file_path': str(zip_path),
                'status': 'success',
            })
            logs = self.Cleanup.cleanup_plan(plan, trigger='manual')
            self.assertFalse(zip_path.exists())
            self.assertTrue(history.exists())
            self.assertTrue(history.file_deleted)
            self.assertTrue(history.file_deleted_datetime)
            self.assertEqual(history.file_storage_status, 'deleted')
            self.assertEqual(logs.files_deleted, 1)
            self.assertTrue(plan.last_cleanup_datetime)

    def test_manual_cleanup_now(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            action = plan.action_cleanup_now()
            self.assertEqual(action['tag'], 'display_notification')

    def test_operators_cannot_cleanup(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            operator = self.env['res.users'].create({
                'name': 'Cleanup Operator',
                'login': 'cb_cleanup_op_%s' % uuid4().hex[:8],
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.operator_group.id,
                ])],
            })
            with self.assertRaises(UserError):
                plan.with_user(operator).action_cleanup_now()

    def test_scheduler_cleanup_and_empty_directory(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            plan.last_cleanup_datetime = False
            cleaned = self.Cleanup.run_due_retention_cleanup()
            self.assertGreaterEqual(cleaned, 1)
            logs = self.env['cb.backup.cleanup.log'].search([('plan_id', '=', plan.id)])
            self.assertTrue(logs)

    def test_missing_directory_does_not_crash(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            Path(local_dir)
            logs = self.Cleanup.cleanup_plan(plan, trigger='manual')
            self.assertEqual(logs.status, 'success')
            self.assertEqual(logs.files_deleted, 0)

    def test_concurrent_running_backup_file_not_deleted(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage, retention_days=1)
            zip_path = self._write_managed_zip(
                Path(local_dir) / plan.get_storage_relative_dir(),
                plan.database_name,
                plan.id,
                datetime(2020, 1, 1, 12, 0, 0),
            )
            self.env['cb.backup.history'].create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'backup_datetime': fields.Datetime.now(),
                'file_name': zip_path.name,
                'file_path': str(zip_path),
                'status': 'running',
            })
            self.Cleanup.cleanup_plan(plan, trigger='manual')
            self.assertTrue(zip_path.exists())

    def test_unsupported_storage_provider_cleanup(self):
        storage = self.Storage.create({
            'name': 'GDrive Cleanup Unsupported %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_account': 'backup@example.com',
        })
        provider = get_storage_provider(storage)
        listed = provider.list_backups(relative_dir='db/plan_1', database_name='db', plan_id=1)
        self.assertEqual(listed.status, 'failed')
        deleted = provider.delete_backup('/tmp/file.zip')
        self.assertEqual(deleted.status, 'failed')

    def test_google_drive_cleanup_requires_authorization(self):
        storage = self.Storage.create({
            'name': 'GDrive Cleanup %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_account': 'backup@example.com',
        })
        provider = get_storage_provider(storage)
        listed = provider.list_backups()
        self.assertEqual(listed.status, 'failed')
