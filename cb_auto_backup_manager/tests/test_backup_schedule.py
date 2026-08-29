# -*- coding: utf-8 -*-
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_schedule import parse_schedule_time
from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    MANIFEST_FILENAME,
    build_backup_manifest,
    calculate_retention_cutoff,
    create_backup_zip,
    generate_backup_filename,
    is_older_than_cutoff,
    write_manifest_file,
)


@tagged('post_install', '-at_install')
class TestBackupSchedulePerDay(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.Service = cls.env['cb.backup.service']
        cls.Cleanup = cls.env['cb.backup.cleanup.service']

    def _create_local_storage(self, path=None):
        if path is None:
            path = tempfile.mkdtemp()
        return self.Storage.create({
            'name': 'Schedule Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _daily_vals(self, hour, minute=0):
        return {
            'frequency': 'daily',
            'time_hour': hour,
            'time_minute': minute,
            'active': True,
        }

    def _create_draft_plan(self, storage, backups_per_day=1, schedule_vals=None):
        if schedule_vals is None:
            schedule_vals = [self._daily_vals(6)]
        return self.Plan.create({
            'name': 'Per Day Plan %s' % uuid4().hex[:8],
            'database_name': self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'backups_per_day': backups_per_day,
            'storage_destination_ids': [(6, 0, [storage.id])],
            'schedule_ids': [(0, 0, vals) for vals in schedule_vals],
        })

    def _ensure_filestore(self, database_name):
        filestore = Path(tempfile.mkdtemp()) / 'filestore' / database_name
        filestore.mkdir(parents=True, exist_ok=True)
        (filestore / 'attachment.bin').write_bytes(b'attachment')
        return filestore

    def test_backups_per_day_one(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(storage, backups_per_day=1, schedule_vals=[self._daily_vals(6)])
            plan.action_activate()
            self.assertEqual(plan.state, 'active')
            self.assertEqual(len(plan.schedule_ids.filtered('active')), 1)

    def test_backups_per_day_two(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=2,
                schedule_vals=[self._daily_vals(8), self._daily_vals(20)],
            )
            plan.action_activate()
            times = sorted(plan.schedule_ids.mapped('time_display'))
            self.assertEqual(times, ['08:00', '20:00'])

    def test_backups_per_day_three(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=3,
                schedule_vals=[
                    self._daily_vals(23),
                    self._daily_vals(6),
                    self._daily_vals(14),
                ],
            )
            plan.action_activate()
            ordered = plan.schedule_ids.sorted(lambda s: (s.time_hour, s.time_minute))
            self.assertEqual(ordered.mapped('time_display'), ['06:00', '14:00', '23:00'])
            self.assertEqual(ordered.mapped('time_hour'), [6, 14, 23])

    def test_backups_per_day_five(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            hours = [6, 10, 14, 18, 23]
            plan = self._create_draft_plan(
                storage,
                backups_per_day=5,
                schedule_vals=[self._daily_vals(hour) for hour in hours],
            )
            plan.action_activate()
            self.assertEqual(
                plan.schedule_ids.sorted(lambda s: s.time_hour).mapped('time_display'),
                ['06:00', '10:00', '14:00', '18:00', '23:00'],
            )

    def test_backups_per_day_ten(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            hours = [0, 2, 4, 6, 8, 10, 12, 14, 18, 22]
            plan = self._create_draft_plan(
                storage,
                backups_per_day=10,
                schedule_vals=[self._daily_vals(hour) for hour in hours],
            )
            plan.action_activate()
            self.assertEqual(len(plan.schedule_ids.filtered('active')), 10)

    def test_midnight_and_end_of_day_times(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=2,
                schedule_vals=[self._daily_vals(0, 0), self._daily_vals(23, 59)],
            )
            plan.action_activate()
            times = plan.schedule_ids.sorted(lambda s: (s.time_hour, s.time_minute))
            self.assertEqual(times.mapped('time_display'), ['00:00', '23:59'])
            self.assertTrue(times[0].is_due(datetime(2026, 8, 13, 0, 0, 30)))
            self.assertTrue(times[1].is_due(datetime(2026, 8, 13, 23, 59, 10)))
            self.assertFalse(times[0].is_due(datetime(2026, 8, 13, 1, 0, 0)))

    def test_plan_timezone_converts_utc_to_local(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(storage, backups_per_day=1, schedule_vals=[self._daily_vals(6)])
            plan.timezone = 'America/New_York'
            plan.action_activate()
            utc_now = datetime(2026, 1, 15, 11, 0, 0)
            with patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_plan.fields.Datetime.now',
                return_value=utc_now,
            ):
                local_now = plan._get_local_now()
            self.assertEqual(local_now.hour, 6)
            self.assertTrue(plan.schedule_ids[:1].is_due(local_now))

    def test_backups_per_day_greater_than_three(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            hours = [2, 8, 12, 18]
            plan = self._create_draft_plan(
                storage,
                backups_per_day=4,
                schedule_vals=[self._daily_vals(hour) for hour in hours],
            )
            plan.action_activate()
            self.assertEqual(len(plan.schedule_ids.filtered('active')), 4)

    def test_zero_backups_per_day_rejected(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            with self.assertRaises(ValidationError):
                self._create_draft_plan(storage, backups_per_day=0)

    def test_negative_backups_per_day_rejected(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            with self.assertRaises(ValidationError):
                self._create_draft_plan(storage, backups_per_day=-1)

    def test_fewer_daily_schedules_than_backups_per_day_rejected(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=3,
                schedule_vals=[self._daily_vals(6), self._daily_vals(14)],
            )
            self.assertTrue(plan.schedule_match_warning)
            with self.assertRaises(UserError):
                plan.action_activate()
            self.assertEqual(plan.state, 'draft')

    def test_more_daily_schedules_than_backups_per_day_rejected(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=3,
                schedule_vals=[
                    self._daily_vals(6),
                    self._daily_vals(10),
                    self._daily_vals(14),
                    self._daily_vals(18),
                ],
            )
            self.assertIn('Remove', plan.schedule_match_warning)
            with self.assertRaises(UserError):
                plan.action_activate()
            self.assertEqual(plan.state, 'draft')
            self.assertEqual(len(plan.schedule_ids), 4)

    def test_duplicate_times_rejected(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            with self.assertRaises(ValidationError):
                self._create_draft_plan(
                    storage,
                    backups_per_day=2,
                    schedule_vals=[self._daily_vals(6), self._daily_vals(6)],
                )

    def test_valid_multiple_daily_times(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=3,
                schedule_vals=[
                    self._daily_vals(6),
                    self._daily_vals(14),
                    self._daily_vals(23),
                ],
            )
            plan.action_activate()
            self.assertFalse(plan.schedule_match_warning)

    def test_weekly_multiple_times(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=2,
                schedule_vals=[
                    {
                        'frequency': 'weekly',
                        'weekday': 'sunday',
                        'time_hour': 8,
                        'time_minute': 0,
                    },
                    {
                        'frequency': 'weekly',
                        'weekday': 'sunday',
                        'time_hour': 20,
                        'time_minute': 0,
                    },
                ],
            )
            plan.action_activate()
            sunday = datetime(2026, 8, 9, 8, 0, 0)  # Sunday
            monday = datetime(2026, 8, 10, 8, 0, 0)
            morning, evening = plan.schedule_ids.sorted(lambda s: s.time_hour)
            self.assertTrue(morning.is_due(sunday))
            self.assertFalse(evening.is_due(sunday))
            self.assertTrue(evening.is_due(sunday.replace(hour=20)))
            self.assertFalse(morning.is_due(monday))

    def test_monthly_multiple_times(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=2,
                schedule_vals=[
                    {
                        'frequency': 'monthly',
                        'month_day': 1,
                        'time_hour': 2,
                        'time_minute': 0,
                    },
                    {
                        'frequency': 'monthly',
                        'month_day': 1,
                        'time_hour': 22,
                        'time_minute': 0,
                    },
                ],
            )
            plan.action_activate()
            day1 = datetime(2026, 8, 1, 2, 0, 0)
            day2 = datetime(2026, 8, 2, 2, 0, 0)
            first, second = plan.schedule_ids.sorted(lambda s: s.time_hour)
            self.assertTrue(first.is_due(day1))
            self.assertTrue(second.is_due(day1.replace(hour=22)))
            self.assertFalse(first.is_due(day2))

    def test_decreasing_backups_per_day_does_not_delete_times(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=3,
                schedule_vals=[
                    self._daily_vals(6),
                    self._daily_vals(14),
                    self._daily_vals(23),
                ],
            )
            plan.write({'backups_per_day': 2})
            self.assertEqual(len(plan.schedule_ids), 3)
            self.assertIn('Remove', plan.schedule_match_warning)

    def test_onchange_adds_daily_times_when_increasing(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(storage, backups_per_day=1)
            with Form(plan) as form:
                form.backups_per_day = 3
            daily = plan.schedule_ids.filtered(lambda s: s.frequency == 'daily' and s.active)
            self.assertEqual(len(daily), 3)
            self.assertIn('06:00', daily.mapped('time_display'))

    def test_parse_schedule_time(self):
        self.assertEqual(parse_schedule_time('6:00'), (6, 0))
        self.assertEqual(parse_schedule_time('14:30'), (14, 30))
        with self.assertRaises(ValidationError):
            parse_schedule_time('25:00')
        with self.assertRaises(ValidationError):
            parse_schedule_time('abc')

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump')
    def test_scheduler_executes_each_configured_time(self, mock_run_pg_dump):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        mock_run_pg_dump.side_effect = _fake_dump
        filestore = self._ensure_filestore(self.env.cr.dbname)

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=3,
                schedule_vals=[
                    self._daily_vals(6),
                    self._daily_vals(14),
                    self._daily_vals(23),
                ],
            )
            plan.action_activate()
            slots = [
                datetime(2026, 8, 11, 6, 0, 0),
                datetime(2026, 8, 11, 14, 0, 0),
                datetime(2026, 8, 11, 23, 0, 0),
            ]
            for slot in slots:
                with patch.object(type(plan), '_get_local_now', return_value=slot), patch.object(
                    type(self.Service),
                    'get_filestore_path',
                    return_value=filestore,
                ):
                    executed = self.Service.run_due_scheduled_backups()
                self.assertEqual(executed, 1, 'Expected one backup at %s' % slot)

            histories = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
                ('trigger_type', '=', 'scheduled'),
            ])
            self.assertEqual(len(histories), 3)
            self.assertEqual(len(set(histories.mapped('schedule_id').ids)), 3)
            self.assertTrue(all(histories.mapped('scheduled_occurrence')))

            with patch.object(type(plan), '_get_local_now', return_value=slots[0]), patch.object(
                type(self.Service),
                'get_filestore_path',
                return_value=filestore,
            ):
                repeated = self.Service.run_due_scheduled_backups()
            self.assertEqual(repeated, 0)
            self.assertEqual(self.env['cb.backup.history'].search_count([
                ('plan_id', '=', plan.id),
                ('trigger_type', '=', 'scheduled'),
            ]), 3)

    @patch('odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump')
    def test_manual_backup_now_remains_independent(self, mock_run_pg_dump):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        mock_run_pg_dump.side_effect = _fake_dump
        filestore = self._ensure_filestore(self.env.cr.dbname)

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=2,
                schedule_vals=[self._daily_vals(8), self._daily_vals(20)],
            )
            plan.action_activate()
            with patch.object(type(self.Service), 'get_filestore_path', return_value=filestore):
                action = plan.action_backup_now()
            self.assertEqual(action['params']['type'], 'success')
            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)])
            self.assertEqual(len(history), 1)
            self.assertEqual(history.trigger_type, 'manual')
            self.assertFalse(history.scheduled_occurrence)

    def test_retention_still_based_on_days(self):
        now = datetime(2026, 8, 12, 23, 0, 0)
        cutoff = calculate_retention_cutoff(now, 30)
        self.assertTrue(is_older_than_cutoff(datetime(2026, 7, 12, 23, 0, 0), cutoff))
        self.assertFalse(is_older_than_cutoff(datetime(2026, 7, 14, 0, 0, 0), cutoff))

        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_draft_plan(
                storage,
                backups_per_day=3,
                schedule_vals=[
                    self._daily_vals(6),
                    self._daily_vals(14),
                    self._daily_vals(23),
                ],
            )
            plan.action_activate()
            relative = Path(plan.get_storage_relative_dir())
            dest = Path(local_dir) / relative
            dest.mkdir(parents=True)
            old_dt = datetime(2026, 7, 1, 6, 0, 0)
            recent_dt = datetime(2026, 8, 10, 6, 0, 0)
            old_zip = self._write_managed_zip(dest, plan.database_name, plan.id, old_dt)
            recent_zip = self._write_managed_zip(dest, plan.database_name, plan.id, recent_dt)
            with patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_cleanup_service.fields.Datetime.now',
                return_value=now,
            ):
                logs = self.Cleanup.cleanup_plan(plan, trigger='manual')
            self.assertFalse(old_zip.exists())
            self.assertTrue(recent_zip.exists())
            self.assertEqual(sum(logs.mapped('files_deleted')), 1)

    def _write_managed_zip(self, directory, database_name, plan_id, backup_dt):
        directory = Path(directory)
        workspace = directory / ('.ws_%s' % uuid4().hex[:6])
        workspace.mkdir()
        (workspace / DATABASE_DUMP_FILENAME).write_bytes(b'dump')
        write_manifest_file(
            workspace / MANIFEST_FILENAME,
            build_backup_manifest(
                database_name=database_name,
                backup_datetime=backup_dt,
                odoo_version='19.0',
                module_version='19.0.3.1.0',
                filestore_included=True,
                plan_id=plan_id,
                plan_identifier='plan_%s' % plan_id,
            ),
        )
        filename = generate_backup_filename(database_name, backup_dt)
        zip_path = directory / filename
        create_backup_zip(workspace, zip_path)
        return zip_path
