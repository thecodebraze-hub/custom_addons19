# -*- coding: utf-8 -*-
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_utils import BackupError


@tagged('post_install', '-at_install')
class TestBackupEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.Service = cls.env['cb.backup.service']
        cls.admin_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_administrator')
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')

    def _create_local_storage(self, path=None):
        if path is None:
            path = tempfile.mkdtemp()
        return self.Storage.create({
            'name': 'Local Engine Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _create_draft_plan(self, storage, dbname=None, with_schedule=True):
        vals = {
            'name': 'Engine Test Plan %s' % uuid4().hex[:8],
            'database_name': dbname or self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'storage_destination_ids': [(6, 0, [storage.id])],
        }
        if with_schedule:
            vals['schedule_ids'] = [(0, 0, {
                'frequency': 'daily',
                'time_hour': 6,
                'time_minute': 0,
            })]
        return self.Plan.create(vals)

    def _create_active_plan(self, storage, dbname=None):
        plan = self._create_draft_plan(storage, dbname=dbname)
        plan.action_activate()
        return plan

    def _ensure_filestore(self, database_name):
        filestore = Path(tempfile.mkdtemp()) / 'filestore' / database_name
        filestore.mkdir(parents=True, exist_ok=True)
        (filestore / 'attachment.bin').write_bytes(b'attachment')
        return filestore

    def test_plan_requires_storage_destination(self):
        with self.assertRaises(ValidationError):
            self.Plan.create({
                'name': 'Missing Storage Plan %s' % uuid4().hex[:8],
                'database_name': self.env.cr.dbname,
                'timezone': 'UTC',
            })

    def test_invalid_database_rejected(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            with self.assertRaises(ValidationError):
                self.Plan.create({
                    'name': 'Invalid DB Plan %s' % uuid4().hex[:8],
                    'database_name': 'this_database_should_not_exist_12345',
                    'timezone': 'UTC',
                    'storage_destination_ids': [(6, 0, [storage.id])],
                })

    def test_schedule_validation(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            with self.assertRaises(ValidationError):
                self.Plan.create({
                    'name': 'Bad Weekly Plan %s' % uuid4().hex[:8],
                    'database_name': self.env.cr.dbname,
                    'timezone': 'UTC',
                    'storage_destination_ids': [(6, 0, [storage.id])],
                    'schedule_ids': [(0, 0, {
                        'frequency': 'weekly',
                        'time_hour': 8,
                        'time_minute': 0,
                    })],
                })

    def test_schedule_due_detection(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            schedule = plan.schedule_ids
            now_local = datetime(2026, 8, 11, 6, 0, 0)
            self.assertTrue(schedule.is_due(now_local))
            schedule.last_run_datetime = datetime(2026, 8, 11, 6, 0, 0)
            self.assertFalse(schedule.is_due(now_local))

    def test_draft_plan_can_be_activated_when_valid(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(storage)
            plan.action_activate()
            self.assertEqual(plan.state, 'active')
            self.assertEqual(storage.validation_status, 'valid')

    def test_invalid_plan_cannot_be_activated_without_schedule(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(storage, with_schedule=False)
            with self.assertRaises(UserError):
                plan.action_activate()
            self.assertEqual(plan.state, 'draft')

    def test_no_active_local_storage_prevents_activation(self):
        gdrive = self.Storage.create({
            'name': 'GDrive Only %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_account': 'backup@example.com',
            'google_drive_folder': 'Odoo Backups',
        })
        plan = self.Plan.create({
            'name': 'GDrive Plan %s' % uuid4().hex[:8],
            'database_name': self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'storage_destination_ids': [(6, 0, [gdrive.id])],
            'schedule_ids': [(0, 0, {
                'frequency': 'daily',
                'time_hour': 6,
                'time_minute': 0,
            })],
        })
        with self.assertRaises(UserError):
            plan.action_activate()
        self.assertEqual(plan.state, 'draft')

    def test_invalid_local_storage_prevents_activation(self):
        storage = self._create_local_storage('relative/not/absolute')
        plan = self._create_draft_plan(storage)
        with self.assertRaises(UserError):
            plan.action_activate()
        self.assertEqual(plan.state, 'draft')

    def test_active_plan_can_be_deactivated(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            plan.action_deactivate()
            self.assertEqual(plan.state, 'inactive')
            self.assertTrue(plan.schedule_ids)
            self.assertTrue(plan.storage_destination_ids)

    def test_draft_plan_cannot_run_scheduled_backup(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(storage)
            result = self.Service.execute_plan_backup(plan, trigger='scheduled')
            self.assertFalse(result)
            self.assertFalse(self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ]))

    def test_inactive_plan_does_not_run(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            plan.action_deactivate()
            result = self.Service.execute_plan_backup(plan, trigger='scheduled')
            self.assertFalse(result)

    def test_scheduler_ignores_inactive_plans(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            plan.action_deactivate()
            now_local = datetime(2026, 8, 11, 6, 0, 0)
            with patch.object(type(plan), '_get_local_now', return_value=now_local):
                executed = self.Service.run_due_scheduled_backups()
            self.assertEqual(executed, 0)

    def test_operators_cannot_activate_deactivate(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(storage)
            operator = self.env['res.users'].create({
                'name': 'Backup Operator',
                'login': 'cb_backup_op_%s' % uuid4().hex[:8],
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.operator_group.id,
                ])],
            })
            with self.assertRaises(UserError):
                plan.with_user(operator).action_activate()
            plan.action_activate()
            with self.assertRaises(UserError):
                plan.with_user(operator).action_deactivate()

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump')
    def test_successful_backup_history(self, mock_run_pg_dump):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        mock_run_pg_dump.side_effect = _fake_dump
        filestore = self._ensure_filestore(self.env.cr.dbname)

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            with patch.object(
                type(self.Service),
                'get_filestore_path',
                return_value=filestore,
            ):
                self.Service.execute_plan_backup(plan, trigger='manual')

            history = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ], limit=1)
            self.assertEqual(history.status, 'success')
            self.assertTrue(history.file_name.endswith('.zip'))
            self.assertTrue(history.checksum)
            self.assertTrue(Path(history.file_path).is_file())

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump')
    def test_backup_now_works_for_active_plan(self, mock_run_pg_dump):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        mock_run_pg_dump.side_effect = _fake_dump
        filestore = self._ensure_filestore(self.env.cr.dbname)

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            with patch.object(
                type(self.Service),
                'get_filestore_path',
                return_value=filestore,
            ):
                action = plan.action_backup_now()
            self.assertEqual(action['tag'], 'display_notification')
            self.assertEqual(action['params']['type'], 'success')

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump')
    def test_missing_filestore_causes_backup_failure(self, mock_run_pg_dump):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        mock_run_pg_dump.side_effect = _fake_dump
        missing = Path(tempfile.gettempdir()) / ('cb_fs_%s' % uuid4().hex[:8]) / 'filestore' / self.env.cr.dbname
        # Intentionally do not create the directory.

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            with patch.object(
                type(self.Service),
                'get_filestore_path',
                return_value=missing,
            ):
                result = self.Service.execute_plan_backup(plan, trigger='scheduled')
            self.assertFalse(result)
            history = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ], limit=1)
            self.assertEqual(history.status, 'failed')
            self.assertIn('Filestore', history.error_message)

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService.validate_database_selection')
    def test_non_existing_database_causes_backup_failure(self, mock_validate):
        mock_validate.side_effect = BackupError(
            'Database "gone_db" does not exist or is not accessible on this Odoo server.'
        )
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self.Plan.create({
                'name': 'Gone DB Plan %s' % uuid4().hex[:8],
                'database_name': self.env.cr.dbname,
                'timezone': 'UTC',
                'state': 'active',
                'storage_destination_ids': [(6, 0, [storage.id])],
                'schedule_ids': [(0, 0, {
                    'frequency': 'daily',
                    'time_hour': 6,
                    'time_minute': 0,
                })],
            })
            result = self.Service.execute_plan_backup(plan, trigger='scheduled')
            self.assertFalse(result)
            history = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ], limit=1)
            self.assertEqual(history.status, 'failed')
            self.assertIn('gone_db', history.error_message)

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.find_pg_tool')
    def test_failed_backup_history_when_pg_dump_missing(self, mock_find_pg_tool):
        mock_find_pg_tool.side_effect = Exception('pg_dump missing')

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            result = self.Service.execute_plan_backup(plan, trigger='scheduled')
            self.assertFalse(result)

            history = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ], limit=1)
            self.assertEqual(history.status, 'failed')
            self.assertIn('pg_dump', history.error_message)

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.find_pg_tool')
    def test_manual_backup_raises_user_error_on_failure(self, mock_find_pg_tool):
        mock_find_pg_tool.side_effect = Exception('pg_dump missing')

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            action = self.Service.execute_plan_backup(plan, trigger='manual')
            self.assertEqual(action['tag'], 'display_notification')
            self.assertEqual(action['params']['type'], 'danger')

    def test_scheduler_continues_after_one_plan_failure(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            broken = self._create_active_plan(storage)
            healthy = self._create_active_plan(storage)
            now_local = datetime(2026, 8, 11, 6, 0, 0)
            calls = []

            def _execute(plan, trigger='scheduled', schedule=None):
                calls.append(plan.id)
                if plan.id == broken.id:
                    raise Exception('simulated plan failure')
                return True

            with patch.object(type(broken), '_get_local_now', return_value=now_local), patch.object(
                type(healthy), '_get_local_now', return_value=now_local,
            ), patch.object(type(self.Service), 'execute_plan_backup', side_effect=_execute):
                executed = self.Service.run_due_scheduled_backups()
            self.assertIn(broken.id, calls)
            self.assertIn(healthy.id, calls)
            self.assertGreaterEqual(executed, 1)

    def test_module_has_no_destructive_uninstall_hook(self):
        from odoo.modules.module import load_manifest
        info = load_manifest('cb_auto_backup_manager')
        self.assertFalse(info.get('uninstall_hook'))
        self.assertFalse(info.get('pre_uninstall_hook'))

    def test_concurrent_backup_protection(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            self.env['cb.backup.history'].create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'backup_datetime': fields.Datetime.now(),
                'start_datetime': fields.Datetime.now(),
                'status': 'running',
            })
            result = self.Service.execute_plan_backup(plan, trigger='manual')
            self.assertFalse(result)

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump')
    def test_scheduler_executes_due_backup(self, mock_run_pg_dump):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        mock_run_pg_dump.side_effect = _fake_dump
        filestore = self._ensure_filestore(self.env.cr.dbname)

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_active_plan(storage)
            schedule = plan.schedule_ids
            now_local = datetime(2026, 8, 11, 6, 0, 0)
            with patch.object(type(plan), '_get_local_now', return_value=now_local), patch.object(
                type(self.Service),
                'get_filestore_path',
                return_value=filestore,
            ):
                self.assertTrue(schedule.is_due(now_local))
                executed = self.Service.run_due_scheduled_backups()

            self.assertEqual(executed, 1)
            self.assertTrue(plan.last_backup_datetime)
