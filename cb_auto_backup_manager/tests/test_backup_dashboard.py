# -*- coding: utf-8 -*-
import json
import tempfile
from datetime import datetime, timedelta
from uuid import uuid4

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestBackupDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.History = cls.env['cb.backup.history']
        cls.Destination = cls.env['cb.backup.history.destination']
        cls.Cleanup = cls.env['cb.backup.cleanup.log']
        cls.Dashboard = cls.env['cb.backup.dashboard']
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')
        cls.admin_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_administrator')

    def _operator(self):
        return self.env['res.users'].create({
            'name': 'Dashboard Operator',
            'login': 'cb_dash_op_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.operator_group.id,
            ])],
        })

    def _admin_user(self):
        return self.env['res.users'].create({
            'name': 'Dashboard Admin',
            'login': 'cb_dash_admin_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.admin_group.id,
            ])],
        })

    def _create_local_storage(self, path=None):
        if path is None:
            path = tempfile.mkdtemp()
        return self.Storage.create({
            'name': 'Dash Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _create_plan(self, storage, state='draft', **kwargs):
        vals = {
            'name': 'Dash Plan %s' % uuid4().hex[:8],
            'database_name': self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'storage_destination_ids': [(6, 0, [storage.id])],
            'schedule_ids': [(0, 0, {
                'frequency': 'daily',
                'time_hour': 23,
                'time_minute': 0,
            })],
        }
        vals.update(kwargs)
        plan = self.Plan.create(vals)
        if state == 'active':
            plan.action_activate()
        elif state == 'inactive':
            plan.action_activate()
            plan.action_deactivate()
        return plan

    def _create_history(self, plan, storage, status='success', **kwargs):
        now = fields.Datetime.now()
        dest_commands = kwargs.pop('destination_result_ids', None)
        vals = {
            'plan_id': plan.id,
            'database_name': plan.database_name,
            'backup_datetime': now,
            'start_datetime': now,
            'end_datetime': now,
            'duration_seconds': 42,
            'file_name': 'company_live_%s.zip' % now.strftime('%Y%m%d_%H%M%S'),
            'file_path': '/managed/backups/%s.zip' % uuid4().hex[:8],
            'file_size': 1024 * 1024,
            'status': status,
            'error_message': kwargs.pop('error_message', False),
            'file_deleted': kwargs.pop('file_deleted', False),
        }
        vals.update(kwargs)
        dest_status = 'success' if status in ('success', 'partial') else 'failed'
        if dest_commands is None:
            dest_commands = [(0, 0, {
                'storage_id': storage.id,
                'storage_name': storage.name,
                'storage_type': storage.type,
                'status': dest_status,
                'file_path': vals['file_path'] if dest_status == 'success' else False,
                'file_size': vals['file_size'] if dest_status == 'success' else 0,
                'error_message': vals.get('error_message') if dest_status != 'success' else False,
            })]
        vals['destination_result_ids'] = dest_commands
        return self.History.create(vals)

    def _open_dashboard(self, env=None):
        dashboard_env = (env or self.env)['cb.backup.dashboard']
        action = dashboard_env.action_open_dashboard()
        return dashboard_env.browse(action['res_id'])

    def test_dashboard_loads_with_no_data(self):
        dash = self._open_dashboard()
        self.assertTrue(dash.exists())
        self.assertGreaterEqual(dash.kpi_total_plans, 0)
        self.assertFalse(dash.has_recent_failures)
        self.assertEqual(dash.failure_empty_message, 'No recent backup failures.')
        self.assertEqual(dash.cleanup_empty_message, 'No cleanup has been performed yet.')
        self.assertIn('No upcoming backups.', dash.kpi_next_backup_display)
        self.assertTrue(dash.activity_graph_data)
        self.assertTrue(dash.storage_graph_data)
        json.loads(dash.activity_graph_data)
        json.loads(dash.storage_graph_data)

    def test_dashboard_loads_with_backup_data(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            self._create_history(plan, storage, status='success')
            dash = self._open_dashboard()
            self.assertGreaterEqual(dash.kpi_total_plans, 1)
            self.assertGreaterEqual(dash.kpi_active_plans, 1)
            self.assertGreaterEqual(dash.kpi_backups_today, 1)
            self.assertTrue(dash.has_today_backups)
            self.assertTrue(dash.recent_history_ids)
            self.assertTrue(dash.storage_ids)

    def test_kpi_counts(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            active = self._create_plan(storage, state='active')
            self._create_plan(storage, state='draft')
            self._create_history(active, storage, status='success', file_size=2048)
            self._create_history(active, storage, status='failed', error_message='dump failed')
            self._create_history(active, storage, status='partial')
            dash = self._open_dashboard()
            self.assertGreaterEqual(dash.kpi_total_plans, 2)
            self.assertGreaterEqual(dash.kpi_active_plans, 1)
            self.assertGreaterEqual(dash.kpi_successful, 1)
            self.assertGreaterEqual(dash.kpi_failed, 1)
            self.assertGreaterEqual(dash.kpi_partial, 1)
            self.assertGreaterEqual(dash.kpi_backups_today, 3)
            self.assertTrue(dash.kpi_total_storage_display)

    def test_todays_backups(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            yesterday = fields.Datetime.now() - timedelta(days=2)
            today = self._create_history(plan, storage, status='success')
            self._create_history(plan, storage, status='failed', backup_datetime=yesterday)
            dash = self._open_dashboard()
            self.assertIn(today, dash.today_history_ids)

    def test_recent_failures(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            failed = self._create_history(
                plan, storage, status='failed', error_message='Upload failed',
            )
            partial = self._create_history(plan, storage, status='partial')
            success = self._create_history(plan, storage, status='success')
            dash = self._open_dashboard()
            self.assertTrue(dash.has_recent_failures)
            self.assertIn(failed, dash.failure_history_ids)
            self.assertIn(partial, dash.failure_history_ids)
            self.assertNotIn(success, dash.failure_history_ids)
            self.assertEqual(failed.error_summary, 'Upload failed')

    def test_recent_failures_empty_state(self):
        dash = self._open_dashboard()
        if not dash.failure_history_ids:
            self.assertFalse(dash.has_recent_failures)
            self.assertEqual(dash.failure_empty_message, 'No recent backup failures.')

    def test_next_scheduled_backup(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            self.assertTrue(plan.next_backup_datetime)
            dash = self._open_dashboard()
            self.assertTrue(dash.has_upcoming_backup)
            self.assertEqual(dash.next_plan_id, plan)
            self.assertEqual(dash.next_database_name, plan.database_name)
            self.assertEqual(dash.next_backup_datetime, plan.next_backup_datetime)
            self.assertNotEqual(dash.kpi_next_backup_display, 'No upcoming backups.')

    def test_storage_destination_status(self):
        with tempfile.TemporaryDirectory() as local_dir:
            ready = self._create_local_storage(local_dir)
            ready.validation_status = 'valid'
            failed = self._create_local_storage(tempfile.mkdtemp())
            failed.validation_status = 'invalid'
            untested = self._create_local_storage(tempfile.mkdtemp())
            archived = self._create_local_storage(tempfile.mkdtemp())
            archived.active = False
            gdrive = self.Storage.create({
                'name': 'Dash GDrive %s' % uuid4().hex[:8],
                'type': 'google_drive',
                'google_drive_folder': 'Backups',
            })
            gdrive.action_validate_storage()
            self.assertEqual(ready.connection_state, 'ready')
            self.assertEqual(failed.connection_state, 'failed')
            self.assertEqual(untested.connection_state, 'not_tested')
            self.assertEqual(archived.connection_state, 'disconnected')
            self.assertEqual(gdrive.connection_state, 'failed')
            self.assertTrue(gdrive.last_test_datetime)
            dash = self._open_dashboard()
            self.assertIn(ready, dash.storage_ids)
            self.assertIn(gdrive, dash.storage_ids)

    def test_cleanup_summary(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            now = fields.Datetime.now()
            self.Cleanup.create({
                'plan_id': plan.id,
                'storage_id': storage.id,
                'cleanup_datetime': now,
                'files_scanned': 10,
                'files_deleted': 3,
                'files_skipped': 1,
                'bytes_deleted': 4096,
                'status': 'success',
            })
            self.Cleanup.create({
                'plan_id': plan.id,
                'storage_id': storage.id,
                'cleanup_datetime': now,
                'files_deleted': 0,
                'bytes_deleted': 0,
                'status': 'failed',
                'error_message': 'remote list failed',
            })
            dash = self._open_dashboard()
            self.assertTrue(dash.has_cleanup)
            self.assertEqual(dash.cleanup_last_datetime, now)
            self.assertEqual(dash.cleanup_files_deleted, 3)
            self.assertEqual(dash.cleanup_failed_count, 1)
            self.assertTrue(dash.cleanup_space_freed_display)

    def test_backup_history_filters(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            success = self._create_history(plan, storage, status='success')
            failed = self._create_history(plan, storage, status='failed', error_message='x')
            deleted = self._create_history(plan, storage, status='success', file_deleted=True)
            old = self._create_history(
                plan, storage, status='success',
                backup_datetime=fields.Datetime.now() - timedelta(days=10),
            )
            self.assertIn(success, self.History.search([('status', '=', 'success')]))
            self.assertIn(failed, self.History.search([('status', '=', 'failed')]))
            self.assertIn(deleted, self.History.search([('file_deleted', '=', True)]))
            available = self.History.search([
                ('file_deleted', '=', False),
                ('status', 'in', ('success', 'partial')),
            ])
            self.assertIn(success, available)
            self.assertNotIn(deleted, available)
            last_7 = self.History.search([
                ('backup_datetime', '>=', fields.Datetime.now() - timedelta(days=7)),
            ])
            self.assertIn(success, last_7)
            self.assertNotIn(old, last_7)
            by_storage = self.History.search([('storage_ids', 'in', [storage.id])])
            self.assertIn(success, by_storage)

    def test_file_deleted_status(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            available = self._create_history(plan, storage, status='success')
            deleted = self._create_history(plan, storage, status='success', file_deleted=True)
            missing = self._create_history(
                plan, storage, status='success', file_path=False,
                destination_result_ids=[(0, 0, {
                    'storage_id': storage.id,
                    'storage_name': storage.name,
                    'storage_type': storage.type,
                    'status': 'success',
                    'file_path': False,
                    'file_size': 0,
                })],
            )
            failed = self._create_history(plan, storage, status='failed', error_message='no zip')
            self.assertEqual(available.file_storage_status, 'available')
            self.assertEqual(deleted.file_storage_status, 'deleted')
            self.assertEqual(missing.file_storage_status, 'missing')
            self.assertEqual(failed.file_storage_status, 'none')

    def test_destination_results(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            history = self.History.create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'backup_datetime': fields.Datetime.now(),
                'file_name': 'company_live_20260813_230000.zip',
                'file_path': '/managed/a.zip',
                'file_size': 1800000000,
                'status': 'partial',
                'destination_result_ids': [
                    (0, 0, {
                        'storage_id': storage.id,
                        'storage_name': 'Local Server',
                        'storage_type': 'local',
                        'status': 'success',
                        'file_size': 1800000000,
                        'file_path': '/managed/a.zip',
                    }),
                    (0, 0, {
                        'storage_name': 'Google Drive',
                        'storage_type': 'google_drive',
                        'status': 'failed',
                        'error_message': 'Upload failed',
                    }),
                ],
            })
            self.assertEqual(len(history.destination_result_ids), 2)
            self.assertIn('Local Server', history.destination_summary)
            self.assertIn('Google Drive', history.destination_summary)
            failed_line = history.destination_result_ids.filtered(lambda line: line.status == 'failed')
            self.assertEqual(failed_line.error_message, 'Upload failed')
            self.assertTrue(history.destination_result_ids[0].file_size_display)

    def test_backup_plan_list(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            self.assertEqual(plan.state, 'active')
            self.assertTrue(plan.storage_destination_ids)
            self.assertTrue(plan.next_backup_datetime)
            view = self.env.ref('cb_auto_backup_manager.view_cb_backup_plan_list')
            arch = view.arch
            self.assertIn('decoration-success="state == \'active\'"', arch)
            self.assertIn('decoration-muted="state == \'inactive\'"', arch)
            self.assertIn('storage_destination_ids', arch)
            self.assertIn('next_backup_datetime', arch)

    def test_storage_destination_list(self):
        view = self.env.ref('cb_auto_backup_manager.view_cb_backup_storage_list')
        arch = view.arch
        self.assertIn('connection_state', arch)
        self.assertIn('last_test_datetime', arch)
        self.assertIn('decoration-success="connection_state == \'ready\'"', arch)

    def test_operator_access(self):
        operator = self._operator()
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, state='active')
            history = self._create_history(plan, storage, status='success')
            dash = self._open_dashboard(self.env(user=operator))
            self.assertTrue(dash.exists())
            self.assertIn(history, dash.recent_history_ids)
            self.assertFalse(dash.can_create_plan)
            self.assertTrue(plan.with_user(operator).name)
            self.assertTrue(history.with_user(operator).status)
            with self.assertRaises(AccessError):
                self.Plan.with_user(operator).create({
                    'name': 'Operator Plan %s' % uuid4().hex[:8],
                    'database_name': self.env.cr.dbname,
                    'timezone': 'UTC',
                    'storage_destination_ids': [(6, 0, [storage.id])],
                })
            with self.assertRaises(AccessError):
                self.env['cb.backup.settings'].with_user(operator).create({})

    def test_administrator_access(self):
        admin = self._admin_user()
        dash = self._open_dashboard(self.env(user=admin))
        self.assertTrue(dash.can_create_plan)
        action = dash.with_user(admin).action_create_plan()
        self.assertEqual(action['res_model'], 'cb.backup.plan')
        settings = self.env['cb.backup.settings'].with_user(admin).action_open_settings()
        self.assertEqual(settings['res_model'], 'cb.backup.settings')

    def test_no_credentials_or_tokens_exposed(self):
        secret_names = {
            'sftp_password',
            'sftp_private_key',
            'sftp_private_key_passphrase',
            'access_token',
            'refresh_token',
            'client_secret',
            'client_id',
            'google_drive_refresh_token',
            'google_drive_access_token',
            'google_drive_client_id',
            'google_drive_client_secret',
            'secret',
            'encryption_secret',
        }
        dashboard_fields = set(self.Dashboard._fields)
        self.assertFalse(secret_names & dashboard_fields)
        form = self.env.ref('cb_auto_backup_manager.view_cb_backup_dashboard_form')
        arch = form.arch
        for name in secret_names:
            self.assertNotIn(name, arch)
        storage = self.Storage.create({
            'name': 'Secret SFTP %s' % uuid4().hex[:8],
            'type': 'sftp',
            'sftp_host': 'backup.example.com',
            'sftp_port': 22,
            'sftp_username': 'backup',
            'sftp_password': 'super-secret-password',
            'sftp_remote_path': '/backups/odoo',
            'sftp_host_key': 'SHA256:testhostkey',
        })
        operator = self._operator()
        try:
            self.assertFalse(storage.with_user(operator).sftp_password)
        except AccessError:
            pass
        dash = self._open_dashboard(self.env(user=operator))
        dumped = json.dumps({
            name: dash[name] for name in dash._fields
            if dash._fields[name].type in ('char', 'text', 'html')
        }, default=str)
        self.assertNotIn('super-secret-password', dumped)

    def test_quick_actions_and_charts(self):
        dash = self._open_dashboard()
        self.assertEqual(dash.action_open_plans()['res_model'], 'cb.backup.plan')
        self.assertEqual(dash.action_open_history()['res_model'], 'cb.backup.history')
        self.assertEqual(dash.action_open_storage()['res_model'], 'cb.backup.storage')
        self.assertEqual(dash.action_open_cleanup_logs()['res_model'], 'cb.backup.cleanup.log')
        backup_now = dash.action_backup_now()
        self.assertEqual(backup_now['res_model'], 'cb.backup.plan')
        self.assertIn(('state', '=', 'active'), backup_now['domain'])
        activity = dash.action_open_activity_graph()
        storage = dash.action_open_storage_graph()
        self.assertEqual(activity['res_model'], 'cb.backup.history')
        self.assertEqual(storage['res_model'], 'cb.backup.history')

    def test_single_scheduler_cron(self):
        crons = self.env['ir.cron'].search([
            ('model_id.model', '=', 'cb.backup.plan'),
        ])
        self.assertEqual(len(crons), 1)
        self.assertEqual(crons.code.strip(), 'model._run_backup_scheduler()')

    def test_dashboard_xml_is_odoo19(self):
        form = self.env.ref('cb_auto_backup_manager.view_cb_backup_dashboard_form')
        root = etree.fromstring(form.arch)
        self.assertIsNotNone(root.find('.//list'))
        self.assertFalse(root.xpath('//*[@attrs]'))
        self.assertFalse(root.xpath('//tree'))
        self.assertIsNotNone(root.find('.//field[@name="failure_empty_message"]'))
        self.assertIn('open_form_view="True"', form.arch)

    def test_menu_order(self):
        dashboard = self.env.ref('cb_auto_backup_manager.menu_cb_backup_dashboard')
        plans = self.env.ref('cb_auto_backup_manager.menu_cb_backup_plans')
        self.assertLess(dashboard.sequence, plans.sequence)
        self.assertEqual(dashboard.name, 'Dashboard')
