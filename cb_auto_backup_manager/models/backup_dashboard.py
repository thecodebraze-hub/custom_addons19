# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from odoo import api, fields, models, _

from odoo.addons.cb_auto_backup_manager.models.backup_utils import format_bytes


class CbBackupDashboard(models.TransientModel):
    _name = 'cb.backup.dashboard'
    _description = 'CB Auto Backup Manager Dashboard'
    _rec_name = 'name'

    name = fields.Char(readonly=True)
    kpi_total_plans = fields.Integer(string='Total Backup Plans', readonly=True)
    kpi_active_plans = fields.Integer(string='Active Backup Plans', readonly=True)
    kpi_backups_today = fields.Integer(string='Backups Today', readonly=True)
    kpi_successful = fields.Integer(string='Successful Backups', readonly=True)
    kpi_failed = fields.Integer(string='Failed Backups', readonly=True)
    kpi_partial = fields.Integer(string='Partial Backups', readonly=True)
    kpi_total_storage_bytes = fields.Float(string='Total Backup Storage (Bytes)', readonly=True)
    kpi_total_storage_display = fields.Char(string='Total Backup Storage', readonly=True)
    kpi_next_backup_display = fields.Char(string='Next Scheduled Backup', readonly=True)

    storage_local_display = fields.Char(string='Local', readonly=True)
    storage_sftp_display = fields.Char(string='SFTP', readonly=True)
    storage_gdrive_display = fields.Char(string='Google Drive', readonly=True)
    storage_usage_note = fields.Char(readonly=True)

    today_history_ids = fields.Many2many(
        'cb.backup.history',
        'cb_backup_dashboard_today_rel',
        'dashboard_id',
        'history_id',
        string="Today's Backups",
        readonly=True,
    )
    recent_history_ids = fields.Many2many(
        'cb.backup.history',
        'cb_backup_dashboard_recent_rel',
        'dashboard_id',
        'history_id',
        string='Recent Backups',
        readonly=True,
    )
    failure_history_ids = fields.Many2many(
        'cb.backup.history',
        'cb_backup_dashboard_failure_rel',
        'dashboard_id',
        'history_id',
        string='Recent Failures',
        readonly=True,
    )
    storage_ids = fields.Many2many(
        'cb.backup.storage',
        'cb_backup_dashboard_storage_rel',
        'dashboard_id',
        'storage_id',
        string='Storage Destinations',
        readonly=True,
    )

    has_today_backups = fields.Boolean(readonly=True)
    has_recent_failures = fields.Boolean(readonly=True)
    today_empty_message = fields.Char(readonly=True)
    failure_empty_message = fields.Char(readonly=True)

    has_upcoming_backup = fields.Boolean(readonly=True)
    next_plan_id = fields.Many2one('cb.backup.plan', string='Plan', readonly=True)
    next_database_name = fields.Char(string='Database', readonly=True)
    next_backup_datetime = fields.Datetime(string='Time', readonly=True)
    next_backup_empty_message = fields.Char(readonly=True)

    has_cleanup = fields.Boolean(readonly=True)
    cleanup_last_datetime = fields.Datetime(string='Last Cleanup', readonly=True)
    cleanup_files_deleted = fields.Integer(string='Files Deleted', readonly=True)
    cleanup_space_freed_display = fields.Char(string='Space Freed', readonly=True)
    cleanup_failed_count = fields.Integer(string='Failed', readonly=True)
    cleanup_empty_message = fields.Char(readonly=True)

    activity_graph_data = fields.Text(readonly=True)
    storage_graph_data = fields.Text(readonly=True)
    storage_trend_note = fields.Char(readonly=True)

    can_create_plan = fields.Boolean(readonly=True)

    last_verification_status = fields.Char(string='Last Backup Verification', readonly=True)
    last_restore_test_status = fields.Char(string='Last Test Restore', readonly=True)
    kpi_encrypted_coverage = fields.Char(string='Encryption Coverage', readonly=True)

    @api.model
    def action_open_dashboard(self):
        dashboard = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('CB Auto Backup Manager Dashboard'),
            'res_model': 'cb.backup.dashboard',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('name', _('Dashboard'))
        records = super().create(vals_list)
        records._load_dashboard_data()
        return records

    def _user_today_bounds(self):
        now = fields.Datetime.now()
        local_now = fields.Datetime.context_timestamp(self, now)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        return start, end

    def _load_dashboard_data(self):
        Plan = self.env['cb.backup.plan']
        History = self.env['cb.backup.history']
        Storage = self.env['cb.backup.storage']
        Cleanup = self.env['cb.backup.cleanup.log']
        Destination = self.env['cb.backup.history.destination']
        RestoreLog = self.env['cb.backup.restore.log']

        today_start, today_end = self._user_today_bounds()
        window_start = today_start - timedelta(days=29)

        plans = Plan.search([])
        active_plans = plans.filtered(lambda plan: plan.state == 'active' and plan.active)

        status_counts = dict(History._read_group(
            [('status', 'in', ('success', 'failed', 'partial'))],
            groupby=['status'],
            aggregates=['__count'],
        ))
        today_count = History.search_count([
            ('backup_datetime', '>=', today_start),
            ('backup_datetime', '<', today_end),
        ])
        storage_sum = History._read_group(
            [
                ('file_deleted', '=', False),
                ('status', 'in', ('success', 'partial')),
            ],
            groupby=[],
            aggregates=['file_size:sum'],
        )
        total_storage = (storage_sum[0][0] if storage_sum else 0.0) or 0.0

        dest_sums = Destination._read_group(
            [
                ('status', '=', 'success'),
                ('file_deleted', '=', False),
            ],
            groupby=['storage_type'],
            aggregates=['file_size:sum'],
        )
        dest_by_type = {storage_type: (size or 0.0) for storage_type, size in dest_sums}

        today_histories = History.search(
            [
                ('backup_datetime', '>=', today_start),
                ('backup_datetime', '<', today_end),
            ],
            order='backup_datetime asc, id asc',
        )
        recent_histories = History.search([], order='backup_datetime desc, id desc', limit=10)
        failure_histories = History.search(
            [('status', 'in', ('failed', 'partial'))],
            order='backup_datetime desc, id desc',
            limit=10,
        )

        next_plan = Plan.search(
            [
                ('state', '=', 'active'),
                ('active', '=', True),
                ('next_backup_datetime', '!=', False),
            ],
            order='next_backup_datetime asc, id asc',
            limit=1,
        )

        last_cleanup = Cleanup.search([], order='cleanup_datetime desc, id desc', limit=1)
        cleanup_batch = Cleanup.browse()
        if last_cleanup:
            batch_start = last_cleanup.cleanup_datetime - timedelta(minutes=5)
            cleanup_batch = Cleanup.search([
                ('cleanup_datetime', '>=', batch_start),
                ('cleanup_datetime', '<=', last_cleanup.cleanup_datetime),
            ])

        storages = Storage.search([], order='name, id')
        is_admin = self.env.user.has_group(
            'cb_auto_backup_manager.group_cb_backup_administrator'
        )
        last_verify = RestoreLog.search(
            [('restore_mode', '=', 'verify_only')],
            order='restore_datetime desc, id desc',
            limit=1,
        )
        last_restore = RestoreLog.search(
            [('restore_mode', '=', 'temporary_restore')],
            order='restore_datetime desc, id desc',
            limit=1,
        )
        verify_labels = {
            'success': _('Verified'),
            'warning': _('Verified'),
            'failed': _('Failed'),
            'running': _('Never Tested'),
        }
        restore_labels = {
            'success': _('Success'),
            'warning': _('Success'),
            'failed': _('Failed'),
            'running': _('Never Tested'),
        }
        stored_count = History.search_count([
            ('status', 'in', ('success', 'partial')),
        ])
        encrypted_count = History.search_count([
            ('status', 'in', ('success', 'partial')),
            ('encrypted', '=', True),
        ])
        coverage = (
            '%s%%' % int(round(100.0 * encrypted_count / stored_count))
            if stored_count else _('n/a')
        )

        for dash in self:
            dash.kpi_total_plans = len(plans)
            dash.kpi_active_plans = len(active_plans)
            dash.kpi_backups_today = today_count
            dash.kpi_successful = status_counts.get('success', 0)
            dash.kpi_failed = status_counts.get('failed', 0)
            dash.kpi_partial = status_counts.get('partial', 0)
            dash.kpi_total_storage_bytes = total_storage
            dash.kpi_total_storage_display = format_bytes(total_storage)
            dash.storage_local_display = format_bytes(dest_by_type.get('local', 0.0))
            dash.storage_sftp_display = format_bytes(dest_by_type.get('sftp', 0.0))
            dash.storage_gdrive_display = format_bytes(dest_by_type.get('google_drive', 0.0))
            dash.storage_usage_note = _(
                'Totals come from backup history of files still marked available. '
                'Remote providers are not scanned when this page loads.'
            )
            dash.today_history_ids = today_histories
            dash.recent_history_ids = recent_histories
            dash.failure_history_ids = failure_histories
            dash.storage_ids = storages
            dash.has_today_backups = bool(today_histories)
            dash.has_recent_failures = bool(failure_histories)
            dash.today_empty_message = _("No backups today.")
            dash.failure_empty_message = _("No recent backup failures.")
            dash.has_upcoming_backup = bool(next_plan)
            dash.next_plan_id = next_plan
            dash.next_database_name = next_plan.database_name if next_plan else False
            dash.next_backup_datetime = next_plan.next_backup_datetime if next_plan else False
            dash.kpi_next_backup_display = (
                fields.Datetime.to_string(next_plan.next_backup_datetime)
                if next_plan else _('No upcoming backups.')
            )
            dash.next_backup_empty_message = _('No upcoming backups.')
            dash.has_cleanup = bool(last_cleanup)
            dash.cleanup_last_datetime = last_cleanup.cleanup_datetime if last_cleanup else False
            dash.cleanup_files_deleted = sum(cleanup_batch.mapped('files_deleted')) if cleanup_batch else 0
            dash.cleanup_space_freed_display = format_bytes(
                sum(cleanup_batch.mapped('bytes_deleted')) if cleanup_batch else 0.0
            )
            dash.cleanup_failed_count = len(cleanup_batch.filtered(lambda log: log.status == 'failed'))
            dash.cleanup_empty_message = _('No cleanup has been performed yet.')
            dash.activity_graph_data = dash._build_activity_graph(History, window_start, today_end)
            dash.storage_graph_data = dash._build_storage_graph(History, window_start, today_end)
            dash.storage_trend_note = _(
                'Daily backup volume from history (successful and partial). '
                'This is not cumulative remaining disk usage after retention deletions.'
            )
            dash.can_create_plan = is_admin
            dash.last_verification_status = (
                verify_labels.get(last_verify.status, _('Never Tested'))
                if last_verify else _('Never Tested')
            )
            dash.last_restore_test_status = (
                restore_labels.get(last_restore.status, _('Never Tested'))
                if last_restore else _('Never Tested')
            )
            dash.kpi_encrypted_coverage = coverage

    def _build_activity_graph(self, History, window_start, window_end):
        rows = History._read_group(
            [
                ('backup_datetime', '>=', window_start),
                ('backup_datetime', '<', window_end),
                ('status', 'in', ('success', 'failed', 'partial')),
            ],
            groupby=['backup_datetime:day', 'status'],
            aggregates=['__count'],
        )
        counts = defaultdict(int)
        for day_value, status, count in rows:
            day = self._group_day(day_value)
            if day and status == 'success':
                counts[day] += count
        values = self._graph_day_values(window_start, window_end, counts)
        return json.dumps([{
            'key': _('Successful'),
            'values': values,
            'is_sample_data': False,
        }])

    def _build_storage_graph(self, History, window_start, window_end):
        rows = History._read_group(
            [
                ('backup_datetime', '>=', window_start),
                ('backup_datetime', '<', window_end),
                ('status', 'in', ('success', 'partial')),
            ],
            groupby=['backup_datetime:day'],
            aggregates=['file_size:sum'],
        )
        sizes = {}
        for day_value, size in rows:
            day = self._group_day(day_value)
            if day:
                sizes[day] = float(size or 0.0)
        values = []
        for day in self._iter_days(window_start, window_end):
            values.append({
                'x': day.strftime('%m-%d'),
                'y': round(sizes.get(day, 0.0) / (1024.0 * 1024.0), 2),
            })
        return json.dumps([{
            'key': _('Backup volume (MB)'),
            'values': values,
            'is_sample_data': False,
        }])

    def _graph_day_values(self, window_start, window_end, counts):
        values = []
        today = self._user_today_bounds()[0].date()
        for day in self._iter_days(window_start, window_end):
            point_type = 'future' if day > today else 'past'
            values.append({
                'label': day.strftime('%m-%d'),
                'value': counts.get(day, 0),
                'type': point_type,
            })
        return values

    def _iter_days(self, window_start, window_end):
        start = window_start.date()
        end = (window_end - timedelta(seconds=1)).date()
        day = start
        while day <= end:
            yield day
            day += timedelta(days=1)

    def _group_day(self, day_value):
        if not day_value:
            return False
        if isinstance(day_value, datetime):
            return day_value.date()
        if isinstance(day_value, str):
            return date.fromisoformat(day_value[:10])
        return day_value

    def action_open_plans(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_plan'
        )
        action['target'] = 'current'
        return action

    def action_open_history(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_history'
        )
        action['target'] = 'current'
        return action

    def action_open_storage(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_storage'
        )
        action['target'] = 'current'
        return action

    def action_open_cleanup_logs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_cleanup_log'
        )
        action['target'] = 'current'
        return action

    def action_create_plan(self):
        self.ensure_one()
        if not self.env.user.has_group(
            'cb_auto_backup_manager.group_cb_backup_administrator'
        ):
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Backup Plan'),
            'res_model': 'cb.backup.plan',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_state': 'draft'},
        }

    def action_backup_now(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_plan'
        )
        action['name'] = _('Backup Now')
        action['domain'] = [('state', '=', 'active')]
        action['context'] = {
            'search_default_filter_active_state': 1,
        }
        action['help'] = _(
            '<p class="o_view_nocontent_smiling_face">No active backup plans</p>'
            '<p>Open an active plan and use Backup Now. This dashboard does not run backups itself.</p>'
        )
        return action

    def action_open_activity_graph(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_history_activity_graph'
        )
        return action

    def action_open_storage_graph(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_history_storage_graph'
        )
        return action

    def action_open_next_plan(self):
        self.ensure_one()
        if not self.next_plan_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Backup Plan'),
            'res_model': 'cb.backup.plan',
            'res_id': self.next_plan_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
