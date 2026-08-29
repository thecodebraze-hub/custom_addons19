# -*- coding: utf-8 -*-
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.services.storage_providers.base import (
    ListBackupsResult,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.local import (
    LocalStorageProvider,
)


@tagged('post_install', '-at_install')
class TestBackupNotifications(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.Service = cls.env['cb.backup.service']
        cls.Notifier = cls.env['cb.backup.notification.service']
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')
        cls.admin_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_administrator')

    def _create_local_storage(self, path):
        return self.Storage.create({
            'name': 'Notify Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _create_active_plan(self, storage, **kwargs):
        vals = {
            'name': 'Notify Plan %s' % uuid4().hex[:8],
            'database_name': self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'storage_destination_ids': [(6, 0, [storage.id])],
            'schedule_ids': [(0, 0, {
                'frequency': 'daily',
                'time_hour': 6,
                'time_minute': 0,
            })],
            'notify_on_success': True,
            'notify_on_failure': True,
            'notify_on_partial': True,
            'notify_on_cleanup_failure': True,
            'notification_user_ids': [(6, 0, [self.env.ref('base.user_admin').id])],
        }
        vals.update(kwargs)
        plan = self.Plan.create(vals)
        plan.action_activate()
        return plan

    def _ensure_filestore(self, database_name):
        filestore = Path(tempfile.mkdtemp()) / 'filestore' / database_name
        filestore.mkdir(parents=True, exist_ok=True)
        (filestore / 'attachment.bin').write_bytes(b'attachment')
        return filestore

    def _inbox(self, model, res_id):
        return self.env['mail.message'].sudo().search([
            ('model', '=', model),
            ('res_id', '=', res_id),
            ('message_type', '=', 'user_notification'),
        ])

    def _operator(self):
        return self.env['res.users'].create({
            'name': 'Notify Operator',
            'login': 'cb_notify_op_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.operator_group.id,
            ])],
        })

    def _run_manual_backup(self, plan):
        filestore = self._ensure_filestore(self.env.cr.dbname)

        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        with patch(
            'odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump',
            side_effect=_fake_dump,
        ), patch.object(type(self.Service), 'get_filestore_path', return_value=filestore):
            return plan.action_backup_now()

    def test_success_notification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(self._create_local_storage(local_dir))
            action = self._run_manual_backup(plan)
            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)], limit=1)
            self.assertEqual(action['params']['type'], 'success')
            self.assertEqual(action['params']['title'], 'Backup Successful')
            self.assertIn('completed successfully', action['params']['message'])
            inbox = self._inbox('cb.backup.history', history.id)
            self.assertTrue(inbox)
            self.assertEqual(inbox[:1].subject, 'Backup Successful')

    def test_failure_notification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(self._create_local_storage(local_dir))
            with patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_service.find_pg_tool',
                side_effect=Exception('pg_dump missing'),
            ):
                action = plan.action_backup_now()
            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)], limit=1)
            self.assertEqual(history.status, 'failed')
            self.assertEqual(action['params']['type'], 'danger')
            self.assertEqual(action['params']['title'], 'Backup Failed')
            inbox = self._inbox('cb.backup.history', history.id)
            self.assertTrue(inbox)
            self.assertIn('Failed', inbox[:1].subject)

    def test_partial_success_notification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            local = self._create_local_storage(local_dir)
            gdrive = self.Storage.create({
                'name': 'GDrive Notify %s' % uuid4().hex[:8],
                'type': 'google_drive',
                'google_drive_account': 'backup@example.com',
            })
            plan = self.Plan.create({
                'name': 'Partial Notify Plan %s' % uuid4().hex[:8],
                'database_name': self.env.cr.dbname,
                'timezone': 'UTC',
                'state': 'active',
                'notify_on_partial': True,
                'notify_on_failure': True,
                'notification_user_ids': [(6, 0, [self.env.ref('base.user_admin').id])],
                'storage_destination_ids': [(6, 0, [local.id, gdrive.id])],
                'schedule_ids': [(0, 0, {'frequency': 'daily', 'time_hour': 1, 'time_minute': 0})],
            })
            action = self._run_manual_backup(plan)
            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)], limit=1)
            self.assertEqual(history.status, 'partial')
            self.assertEqual(action['params']['type'], 'warning')
            self.assertEqual(action['params']['title'], 'Backup Partially Completed')
            inbox = self._inbox('cb.backup.history', history.id)
            self.assertTrue(inbox)
            self.assertIn('Partially', inbox[:1].subject)

    def test_cleanup_failure_notification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(self._create_local_storage(local_dir))
            failed = ListBackupsResult(
                success=False,
                destination=plan.storage_destination_ids[:1].name,
                status='failed',
                error_message='SFTP remote directory is not writable.',
            )
            with patch.object(LocalStorageProvider, 'list_backups', return_value=failed):
                action = plan.action_cleanup_now()
            self.assertEqual(action['params']['type'], 'danger')
            self.assertIn('failed', action['params']['title'].lower())
            logs = self.env['cb.backup.cleanup.log'].search([('plan_id', '=', plan.id)])
            self.assertTrue(logs)
            inbox = self._inbox('cb.backup.cleanup.log', logs[:1].id)
            self.assertTrue(inbox)

    def test_notification_recipients(self):
        operator = self._operator()
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(
                self._create_local_storage(local_dir),
                notification_user_ids=[(6, 0, [operator.id])],
            )
            self._run_manual_backup(plan)
            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)], limit=1)
            inbox = self._inbox('cb.backup.history', history.id)
            self.assertTrue(inbox)
            self.assertIn(operator.partner_id.id, inbox[:1].partner_ids.ids)
            self.assertNotIn(self.env.user.partner_id.id, inbox[:1].partner_ids.ids)

    def test_disabled_notifications(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(
                self._create_local_storage(local_dir),
                notify_on_success=False,
                notify_on_failure=False,
                notify_on_partial=False,
                notify_on_cleanup_failure=False,
            )
            self._run_manual_backup(plan)
            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)], limit=1)
            self.assertFalse(self._inbox('cb.backup.history', history.id))

    def test_scheduled_backup_notification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(self._create_local_storage(local_dir))
            schedule = plan.schedule_ids[:1]
            filestore = self._ensure_filestore(self.env.cr.dbname)

            def _fake_dump(db_name, dump_path):
                Path(dump_path).write_bytes(b'fake-dump')

            with patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump',
                side_effect=_fake_dump,
            ), patch.object(type(self.Service), 'get_filestore_path', return_value=filestore):
                result = self.Service.execute_plan_backup(
                    plan, trigger='scheduled', schedule=schedule,
                )
            self.assertTrue(result)
            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)], limit=1)
            self.assertEqual(history.trigger_type, 'scheduled')
            inbox = self._inbox('cb.backup.history', history.id)
            self.assertTrue(inbox)
            self.assertIn(plan.name, inbox[:1].body)
            self.assertIn(plan.database_name, inbox[:1].body)

    def test_duplicate_notification_prevention(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(self._create_local_storage(local_dir))
            schedule = plan.schedule_ids[:1]
            with patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_service.find_pg_tool',
                side_effect=Exception('pg_dump missing'),
            ):
                fake_now = datetime(2026, 8, 13, 6, 0, 0)
                with patch.object(type(plan), '_get_local_now', return_value=fake_now):
                    self.Service.execute_plan_backup(plan, trigger='scheduled', schedule=schedule)
                    self.Service.execute_plan_backup(plan, trigger='scheduled', schedule=schedule)
            histories = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)])
            self.assertEqual(len(histories), 1)
            inbox = self._inbox('cb.backup.history', histories.id)
            self.assertEqual(len(inbox), 1)

            self.Notifier.notify_backup(plan, histories)
            inbox_after = self._inbox('cb.backup.history', histories.id)
            self.assertEqual(len(inbox_after), 1)

    def test_sensitive_credentials_never_appear(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(self._create_local_storage(local_dir))
            history = self.env['cb.backup.history'].create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'backup_datetime': datetime(2026, 8, 13, 23, 0, 0),
                'status': 'failed',
                'error_message': 'Authentication failed password=secret123 access_token=tok-xyz',
            })
            self.Notifier.notify_backup(plan, history)
            inbox = self._inbox('cb.backup.history', history.id)
            self.assertTrue(inbox)
            self.assertNotIn('secret123', inbox[:1].body or '')
            self.assertNotIn('tok-xyz', inbox[:1].body or '')
            self.assertNotIn('secret123', inbox[:1].subject or '')

    def test_manual_backup_now_notification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            plan = self._create_active_plan(self._create_local_storage(local_dir))
            action = self._run_manual_backup(plan)
            self.assertEqual(action['type'], 'ir.actions.client')
            self.assertEqual(action['tag'], 'display_notification')
            self.assertEqual(action['params']['type'], 'success')

    def test_test_connection_notification(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            action = storage.action_validate_storage()
            self.assertEqual(action['tag'], 'display_notification')
            self.assertEqual(action['params']['type'], 'success')
            self.assertEqual(action['params']['message'], 'Storage connection successful.')
            self.assertEqual(storage.validation_status, 'valid')
            self.assertEqual(storage.connection_state, 'ready')
            self.assertEqual(action['params']['next']['res_model'], 'cb.backup.storage')
            self.assertEqual(action['params']['next']['res_id'], storage.id)

            missing = self.Storage.create({
                'name': 'Bad Local Notify %s' % uuid4().hex[:8],
                'type': 'local',
                'local_path': '/this/path/should/not/exist-%s' % uuid4().hex[:8],
            })
            failed = missing.action_validate_storage()
            self.assertEqual(failed['params']['type'], 'danger')
            self.assertIn('Storage connection failed.', failed['params']['message'])
            self.assertEqual(missing.validation_status, 'invalid')
            self.assertEqual(failed['params']['next']['res_id'], missing.id)

        gdrive = self.Storage.create({
            'name': 'GDrive Test Notify %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_account': 'backup@example.com',
        })
        gdrive_action = gdrive.action_test_connection()
        self.assertEqual(gdrive_action['tag'], 'display_notification')
        self.assertIn('Storage connection failed.', gdrive_action['params']['message'])
        self.assertNotIn('password', (gdrive_action['params']['message'] or '').lower())
