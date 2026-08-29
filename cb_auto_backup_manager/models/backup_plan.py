# -*- coding: utf-8 -*-
"""
Timezone strategy:
Schedule times on a backup plan are evaluated in the plan's IANA timezone field.
Activation requires at least one valid Local Server, SFTP, or Google Drive destination.
Google Drive destinations must be connected (Client ID, Client Secret, Connect Google Drive) before activation.
"""
import logging

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.base.models.res_partner import _tz_get

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    BackupError,
    classify_backup_outcome,
    plan_relative_storage_dir,
    sanitize_error_message,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)

_logger = logging.getLogger(__name__)


class CbBackupPlan(models.Model):
    _name = 'cb.backup.plan'
    _description = 'Backup Plan'
    _order = 'name, id'

    name = fields.Char(
        string='Plan Name',
        required=True,
        help='Descriptive name for this backup plan.',
    )
    active = fields.Boolean(default=True)
    database_name = fields.Selection(
        selection='_selection_database_name',
        string='Database',
        required=True,
        help='PostgreSQL database available on this Odoo server.',
    )
    timezone = fields.Selection(
        selection=_tz_get,
        string='Schedule Timezone',
        required=True,
        default=lambda self: self.env.user.tz or 'UTC',
        help=(
            'IANA timezone used to evaluate schedule times for this plan. '
            'Schedule hours are interpreted in this timezone.'
        ),
    )
    backups_per_day = fields.Integer(
        string='Backups Per Day',
        required=True,
        default=1,
        help='Number of automatic backups scheduled for each applicable day.',
    )
    retention_days = fields.Integer(
        string='Retention (Days)',
        required=True,
        default=30,
        help='Number of days to keep backup files before retention cleanup.',
    )
    schedule_match_warning = fields.Text(
        string='Schedule Warning',
        compute='_compute_schedule_match_warning',
    )
    compression_format = fields.Selection(
        selection=[
            ('zip', 'ZIP'),
        ],
        string='Compression Format',
        required=True,
        default='zip',
    )
    encryption_enabled = fields.Boolean(
        string='Encryption Enabled',
        default=False,
        help='Encrypt the completed backup archive with AES-256 before storage.',
    )
    encryption_method = fields.Selection(
        selection=[
            ('none', 'No Encryption'),
            ('aes256', 'AES-256'),
        ],
        string='Encryption Method',
        required=True,
        default='none',
    )
    encryption_profile_id = fields.Many2one(
        'cb.backup.encryption.profile',
        string='Encryption Profile',
        ondelete='set null',
        help='Reusable encryption secret used when encryption is enabled.',
    )
    encryption_warning = fields.Text(
        compute='_compute_encryption_warning',
    )
    storage_destination_ids = fields.Many2many(
        'cb.backup.storage',
        'cb_backup_plan_storage_rel',
        'plan_id',
        'storage_id',
        string='Storage Destinations',
        help='One backup ZIP is delivered to each selected active destination.',
    )
    notify_on_success = fields.Boolean(
        string='Notify on Success',
        default=False,
    )
    notify_on_failure = fields.Boolean(
        string='Notify on Failure',
        default=True,
    )
    notify_on_partial = fields.Boolean(
        string='Notify on Partial Success',
        default=True,
    )
    notify_on_cleanup_failure = fields.Boolean(
        string='Notify on Cleanup Failure',
        default=True,
    )
    notification_user_ids = fields.Many2many(
        'res.users',
        'cb_backup_plan_notify_user_rel',
        'plan_id',
        'user_id',
        string='Notification Users',
        domain="[('share', '=', False), ('active', '=', True)]",
        help='Users who receive Discuss notifications for this plan. Only Backup Administrators and Backup Operators are notified.',
    )
    schedule_ids = fields.One2many(
        'cb.backup.schedule',
        'plan_id',
        string='Schedules',
    )
    history_ids = fields.One2many(
        'cb.backup.history',
        'plan_id',
        string='Backup History',
    )
    last_backup_datetime = fields.Datetime(
        string='Last Backup',
        readonly=True,
    )
    last_cleanup_datetime = fields.Datetime(
        string='Last Cleanup',
        readonly=True,
    )
    cleanup_log_ids = fields.One2many(
        'cb.backup.cleanup.log',
        'plan_id',
        string='Cleanup Logs',
        readonly=True,
    )
    next_backup_datetime = fields.Datetime(
        string='Next Backup',
        readonly=True,
        compute='_compute_next_backup_datetime',
        store=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        string='Status',
        required=True,
        default='draft',
    )

    _retention_days_positive = models.Constraint(
        'CHECK(retention_days > 0)',
        'Retention days must be greater than zero.',
    )
    _backups_per_day_positive = models.Constraint(
        'CHECK(backups_per_day > 0)',
        'Backups per day must be greater than zero.',
    )
    _name_unique = models.Constraint(
        'UNIQUE(name)',
        'A backup plan with this name already exists.',
    )

    PREFERRED_DAILY_HOURS = (6, 14, 22, 2, 10, 18, 0, 8, 12, 16, 20, 4)

    @api.model
    def _selection_database_name(self):
        service = self.env['cb.backup.service']
        try:
            return [(db, db) for db in service.list_available_databases()]
        except Exception:
            _logger.exception('Unable to build database selection list.')
            current = self.env.cr.dbname
            return [(current, current)] if current else []

    @api.depends('schedule_ids.active', 'schedule_ids.frequency', 'schedule_ids.weekday',
                 'schedule_ids.month_day', 'schedule_ids.time_hour', 'schedule_ids.time_minute',
                 'timezone', 'state', 'active')
    def _compute_next_backup_datetime(self):
        for plan in self:
            plan.next_backup_datetime = plan._compute_next_run_datetime()

    @api.depends(
        'backups_per_day',
        'schedule_ids',
        'schedule_ids.active',
        'schedule_ids.frequency',
        'schedule_ids.weekday',
        'schedule_ids.month_day',
        'schedule_ids.time_hour',
        'schedule_ids.time_minute',
    )
    def _compute_schedule_match_warning(self):
        for plan in self:
            errors = plan._get_schedule_count_errors()
            plan.schedule_match_warning = '\n'.join(errors) if errors else False

    @api.depends('encryption_enabled')
    def _compute_encryption_warning(self):
        warning = _(
            'Encrypted backups require the encryption secret for restore. '
            'Store the secret securely outside the Odoo server.'
        )
        for plan in self:
            plan.encryption_warning = warning if plan.encryption_enabled else False

    @api.onchange('encryption_enabled')
    def _onchange_encryption_enabled(self):
        if self.encryption_enabled:
            self.encryption_method = 'aes256'
        else:
            self.encryption_method = 'none'
            self.encryption_profile_id = False

    @api.onchange('backups_per_day')
    def _onchange_backups_per_day(self):
        """Add missing daily times when the count increases. Never auto-delete."""
        if not self.backups_per_day or self.backups_per_day <= 0:
            return
        daily = self.schedule_ids.filtered(lambda s: s.frequency == 'daily' and s.active)
        other_active = self.schedule_ids.filtered(
            lambda s: s.active and s.frequency != 'daily'
        )
        if other_active and not daily:
            return
        missing = self.backups_per_day - len(daily)
        if missing <= 0:
            return
        used = {(schedule.time_hour, schedule.time_minute) for schedule in daily}
        Schedule = self.env['cb.backup.schedule']
        additions = Schedule
        for hour, minute in self._suggest_daily_backup_times(used, missing):
            additions |= Schedule.new({
                'frequency': 'daily',
                'time_hour': hour,
                'time_minute': minute,
                'active': True,
                'weekday': False,
                'month_day': False,
            })
        if additions:
            self.schedule_ids |= additions

    @api.constrains('retention_days')
    def _check_retention_days(self):
        for plan in self:
            if not plan.retention_days or plan.retention_days <= 0:
                raise ValidationError(_('Retention days must be greater than zero.'))

    @api.constrains('backups_per_day')
    def _check_backups_per_day(self):
        for plan in self:
            if not plan.backups_per_day or plan.backups_per_day <= 0:
                raise ValidationError(_('Backups per day must be greater than zero.'))

    @api.constrains('backups_per_day', 'schedule_ids', 'state')
    def _check_active_plan_schedule_count(self):
        for plan in self.filtered(lambda p: p.state == 'active'):
            errors = plan._get_schedule_count_errors()
            if errors:
                raise ValidationError('\n'.join(errors))

    @api.constrains('name', 'database_name')
    def _check_required_fields(self):
        service = self.env['cb.backup.service']
        for plan in self:
            if not (plan.name or '').strip():
                raise ValidationError(_('Plan name must not be empty.'))
            if not plan.database_name:
                raise ValidationError(_('Database must be selected.'))
            if not service.database_exists(plan.database_name):
                raise ValidationError(
                    _('Database "%s" does not exist or is not accessible.') % plan.database_name
                )

    @api.constrains('storage_destination_ids')
    def _check_storage_destinations(self):
        for plan in self:
            if not plan.storage_destination_ids:
                raise ValidationError(_('At least one storage destination is required.'))

    @api.constrains('encryption_enabled', 'encryption_profile_id', 'encryption_method')
    def _check_encryption_configuration(self):
        for plan in self:
            if not plan.encryption_enabled:
                continue
            if plan.encryption_method != 'aes256':
                raise ValidationError(_('AES-256 encryption is required when encryption is enabled.'))
            if not plan.encryption_profile_id:
                raise ValidationError(_('An encryption profile is required when encryption is enabled.'))
            if not plan.encryption_profile_id.active:
                raise ValidationError(_('The selected encryption profile must be active.'))
            if not plan.encryption_profile_id.sudo()._get_plaintext_secret():
                raise ValidationError(_('The encryption profile does not have a password configured.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('storage_destination_ids'):
                raise ValidationError(_('At least one storage destination is required.'))
            if vals.get('retention_days') is not None and vals.get('retention_days') <= 0:
                raise ValidationError(_('Retention days must be greater than zero.'))
            if vals.get('backups_per_day') is not None and vals.get('backups_per_day') <= 0:
                raise ValidationError(_('Backups per day must be greater than zero.'))
            if not vals.get('notification_user_ids'):
                vals['notification_user_ids'] = [(6, 0, [self._default_notification_user().id])]
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('retention_days') is not None and vals.get('retention_days') <= 0:
            raise ValidationError(_('Retention days must be greater than zero.'))
        if vals.get('backups_per_day') is not None and vals.get('backups_per_day') <= 0:
            raise ValidationError(_('Backups per day must be greater than zero.'))
        if vals.get('encryption_enabled') is False:
            vals.setdefault('encryption_method', 'none')
            vals.setdefault('encryption_profile_id', False)
        elif vals.get('encryption_enabled') is True:
            vals.setdefault('encryption_method', 'aes256')
        return super().write(vals)

    def action_activate(self):
        for plan in self:
            plan._check_backup_admin_access()
            plan._validate_for_activation()
            plan.write({'state': 'active'})
        return True

    def action_deactivate(self):
        for plan in self:
            plan._check_backup_admin_access()
            if plan.state != 'active':
                raise UserError(_('Only active backup plans can be deactivated.'))
            plan.write({'state': 'inactive'})
        return True

    def action_backup_now(self):
        self.ensure_one()
        self._check_backup_execute_access()
        service = self.env['cb.backup.service']
        return service.execute_plan_backup(self, trigger='manual')

    def action_cleanup_now(self):
        self.ensure_one()
        self._check_backup_admin_access()
        if self.state != 'active':
            raise UserError(_('Only active backup plans can run retention cleanup.'))
        if not self.retention_days or self.retention_days <= 0:
            raise UserError(_('Retention days must be greater than zero.'))
        try:
            logs = self.env['cb.backup.cleanup.service'].cleanup_plan(
                self,
                trigger='manual',
            )
        except BackupError as exc:
            raise UserError(str(exc)) from exc
        notifier = self.env['cb.backup.notification.service']
        notifier.notify_cleanup(self, logs, trigger='manual')
        return notifier.build_cleanup_client_action(self, logs)

    @api.model
    def _run_backup_scheduler(self):
        backup_service = self.env['cb.backup.service']
        cleanup_service = self.env['cb.backup.cleanup.service']
        backup_service.run_due_scheduled_backups()
        cleanup_service.run_due_retention_cleanup()
        return True

    def get_storage_relative_dir(self):
        self.ensure_one()
        return plan_relative_storage_dir(self.database_name, self.id)

    def _validate_for_activation(self):
        """Validate that a plan can safely be activated."""
        self.ensure_one()
        service = self.env['cb.backup.service']
        errors = []

        if not (self.name or '').strip():
            errors.append(_('Plan name must not be empty.'))
        if not self.database_name:
            errors.append(_('Database must be selected.'))
        else:
            try:
                service.validate_database_selection(self.database_name)
            except BackupError as exc:
                errors.append(str(exc))

        if not self.retention_days or self.retention_days <= 0:
            errors.append(_('Retention days must be greater than zero.'))
        if not self.backups_per_day or self.backups_per_day <= 0:
            errors.append(_('Backups per day must be greater than zero.'))

        active_schedules = self.schedule_ids.filtered('active')
        if not active_schedules:
            errors.append(_('At least one active schedule is required.'))
        else:
            for schedule in active_schedules:
                if schedule.time_hour < 0 or schedule.time_hour > 23:
                    errors.append(_('Schedule hour must be between 0 and 23.'))
                if schedule.time_minute < 0 or schedule.time_minute > 59:
                    errors.append(_('Schedule minute must be between 0 and 59.'))
                if schedule.frequency == 'weekly' and not schedule.weekday:
                    errors.append(_('Weekly schedules must specify a weekday.'))
                if schedule.frequency == 'monthly' and not schedule.month_day:
                    errors.append(_('Monthly schedules must specify a day of the month.'))
            errors.extend(self._get_schedule_count_errors())

        active_destinations = self.storage_destination_ids.filtered('active')
        if not active_destinations:
            errors.append(_('At least one active storage destination is required.'))
        else:
            unsupported = active_destinations.filtered(
                lambda d: d.type not in ('local', 'sftp', 'google_drive')
            )
            if unsupported:
                errors.append(_(
                    'Active storage destinations must be Local Server, SFTP, or Google Drive. '
                    'Deactivate or remove unsupported destinations (%s).'
                ) % ', '.join(unsupported.mapped('name')))

            supported = active_destinations.filtered(
                lambda d: d.type in ('local', 'sftp', 'google_drive')
            )
            if not supported:
                errors.append(_(
                    'At least one valid Local Server, SFTP, or Google Drive storage destination '
                    'is required before activating a backup plan.'
                ))
            for storage in supported:
                try:
                    provider = get_storage_provider(storage)
                    validated = provider.validate()
                    if storage.type == 'local':
                        message = _('Local storage is valid: %s') % validated
                    elif storage.type == 'sftp':
                        message = _('SFTP connection successful.')
                    else:
                        message = _('Google Drive connection successful.')
                    storage.write({
                        'validation_status': 'valid',
                        'validation_message': message,
                    })
                    if storage.type == 'google_drive':
                        storage.write({'google_drive_connection_status': 'connected'})
                except Exception as exc:
                    errors.append(
                        _('Storage "%s" is not valid: %s') % (
                            storage.name,
                            sanitize_error_message(str(exc)),
                        )
                    )

        try:
            self._check_encryption_ready()
        except BackupError as exc:
            errors.append(str(exc))

        if errors:
            raise UserError('\n'.join(errors))

    def _validate_for_backup(self):
        self.ensure_one()
        service = self.env['cb.backup.service']
        if not self.active or self.state != 'active':
            raise BackupError('Backup plan must be active before running a backup.')
        active_destinations = self.storage_destination_ids.filtered('active')
        if not active_destinations:
            raise BackupError('At least one active storage destination is required.')
        supported = active_destinations.filtered(lambda d: d.type in ('local', 'sftp'))
        if not supported:
            raise BackupError(
                'At least one active Local Server or SFTP storage destination is required.'
            )
        for storage in supported:
            try:
                provider = get_storage_provider(storage)
                if storage.type == 'sftp':
                    provider.validate(connect=False)
                else:
                    provider.validate()
            except Exception as exc:
                raise BackupError(
                    'Storage "%s" is not valid: %s'
                    % (storage.name, sanitize_error_message(str(exc)))
                ) from exc
        service.validate_database_selection(self.database_name)
        self._check_encryption_ready()

    def _check_encryption_ready(self):
        self.ensure_one()
        if not self.encryption_enabled:
            return
        if self.encryption_method != 'aes256':
            raise BackupError('AES-256 encryption is required when encryption is enabled.')
        profile = self.encryption_profile_id.sudo()
        if not profile or not profile.active:
            raise BackupError('A valid active encryption profile is required.')
        if not profile._get_plaintext_secret():
            raise BackupError('The encryption profile does not have a password configured.')

    def _has_running_backup(self):
        self.ensure_one()
        return bool(self.env['cb.backup.history'].search_count([
            ('plan_id', '=', self.id),
            ('status', '=', 'running'),
        ]))

    def _create_running_history(self, trigger='manual', schedule=None, scheduled_occurrence=False):
        self.ensure_one()
        return self.env['cb.backup.history'].create({
            'plan_id': self.id,
            'database_name': self.database_name,
            'backup_datetime': fields.Datetime.now(),
            'start_datetime': fields.Datetime.now(),
            'status': 'running',
            'trigger_type': trigger,
            'schedule_id': schedule.id if schedule else False,
            'scheduled_occurrence': scheduled_occurrence or False,
            'encrypted': bool(self.encryption_enabled),
            'encryption_method': self.encryption_method if self.encryption_enabled else 'none',
        })

    def _finalize_backup_history(self, history, result):
        self.ensure_one()
        destination_results = result.get('destination_results') or []
        line_vals = []
        for dest_result in destination_results:
            storage_id = (dest_result.metadata or {}).get('storage_id')
            storage = self.env['cb.backup.storage'].browse(storage_id) if storage_id else False
            line_vals.append({
                'storage_id': storage.id if storage else False,
                'storage_name': dest_result.destination,
                'storage_type': storage.type if storage else False,
                'status': dest_result.status,
                'file_path': dest_result.final_path,
                'file_size': dest_result.file_size,
                'error_message': sanitize_error_message(dest_result.error_message) if dest_result.error_message else False,
                'started': dest_result.started,
                'completed': dest_result.completed,
            })

        duration = 0.0
        if result.get('start_datetime') and result.get('end_datetime'):
            duration = (
                fields.Datetime.to_datetime(result['end_datetime'])
                - fields.Datetime.to_datetime(result['start_datetime'])
            ).total_seconds()

        history.write({
            'database_name': result.get('database_name') or self.database_name,
            'end_datetime': result.get('end_datetime') or fields.Datetime.now(),
            'duration_seconds': duration,
            'file_name': result.get('filename'),
            'file_path': result.get('file_path'),
            'file_size': result.get('file_size') or 0.0,
            'checksum': result.get('checksum'),
            'encrypted': bool(result.get('encrypted')),
            'encryption_method': result.get('encryption_method') or 'none',
            'status': self._backup_history_status(result),
            'error_message': result.get('error_message'),
            'destination_result_ids': [(0, 0, vals) for vals in line_vals],
        })

    def _backup_history_status(self, result):
        if result.get('destination_results'):
            return classify_backup_outcome(result.get('destination_results'))
        return 'success' if result.get('success') else 'failed'

    def _update_backup_datetimes(self, success, schedule=None):
        self.ensure_one()
        if success:
            now = fields.Datetime.now()
            if schedule:
                schedule.write({'last_run_datetime': now})
            self.write({'last_backup_datetime': now})

    def _get_module_version(self):
        module = self.env['ir.module.module'].search([
            ('name', '=', 'cb_auto_backup_manager'),
        ], limit=1)
        return module.latest_version or '19.0.13.0.0'

    def _get_due_schedules(self):
        self.ensure_one()
        now_local = self._get_local_now()
        return self.schedule_ids.filtered(lambda schedule: schedule.is_due(now_local))

    def _get_schedule_count_errors(self):
        """Return human-readable mismatches between backups_per_day and schedule lines."""
        self.ensure_one()
        errors = []
        expected = self.backups_per_day
        if not expected or expected <= 0:
            return [_('Backups per day must be greater than zero.')]

        active = self.schedule_ids.filtered('active')
        if not active:
            return [_('At least one active schedule is required.')]

        daily = active.filtered(lambda s: s.frequency == 'daily')
        if daily and len(daily) != expected:
            if len(daily) < expected:
                errors.append(_(
                    'Backups Per Day is %(expected)s, but this plan has only %(actual)s '
                    'active daily time(s). Add %(missing)s daily schedule line(s), or lower '
                    'Backups Per Day.'
                ) % {
                    'expected': expected,
                    'actual': len(daily),
                    'missing': expected - len(daily),
                })
            else:
                errors.append(_(
                    'Backups Per Day is %(expected)s, but this plan has %(actual)s '
                    'active daily time(s). Remove %(extra)s daily schedule line(s), or '
                    'increase Backups Per Day. Existing times are not deleted automatically.'
                ) % {
                    'expected': expected,
                    'actual': len(daily),
                    'extra': len(daily) - expected,
                })

        weekly_by_day = {}
        for schedule in active.filtered(lambda s: s.frequency == 'weekly' and s.weekday):
            weekly_by_day.setdefault(schedule.weekday, self.env['cb.backup.schedule'])
            weekly_by_day[schedule.weekday] |= schedule
        weekday_field = self.env['cb.backup.schedule']._fields['weekday']
        weekday_selection = weekday_field.selection
        if callable(weekday_selection):
            weekday_selection = weekday_selection(self.env['cb.backup.schedule'])
        weekday_labels = dict(weekday_selection or [])
        for weekday, lines in weekly_by_day.items():
            if len(lines) != expected:
                errors.append(_(
                    'Weekly schedule for %(day)s has %(actual)s time(s), but Backups Per Day '
                    'is %(expected)s. Add or remove times for that weekday so they match.'
                ) % {
                    'day': weekday_labels.get(weekday, weekday),
                    'actual': len(lines),
                    'expected': expected,
                })

        monthly_by_day = {}
        for schedule in active.filtered(lambda s: s.frequency == 'monthly' and s.month_day):
            monthly_by_day.setdefault(schedule.month_day, self.env['cb.backup.schedule'])
            monthly_by_day[schedule.month_day] |= schedule
        for month_day, lines in monthly_by_day.items():
            if len(lines) != expected:
                errors.append(_(
                    'Monthly schedule for day %(day)s has %(actual)s time(s), but Backups Per '
                    'Day is %(expected)s. Add or remove times for that day so they match.'
                ) % {
                    'day': month_day,
                    'actual': len(lines),
                    'expected': expected,
                })

        return errors

    def _suggest_daily_backup_times(self, used_times, count):
        """Suggest unused HH:MM tuples, preferring common backup hours."""
        used = set(used_times or [])
        suggested = []
        for hour in self.PREFERRED_DAILY_HOURS:
            if len(suggested) >= count:
                break
            candidate = (hour, 0)
            if candidate not in used:
                used.add(candidate)
                suggested.append(candidate)
        hour = 0
        minute = 0
        while len(suggested) < count:
            candidate = (hour, minute)
            if candidate not in used:
                used.add(candidate)
                suggested.append(candidate)
            minute += 15
            if minute >= 60:
                minute = 0
                hour += 1
            if hour >= 24:
                break
        return suggested

    def _get_local_now(self):
        self.ensure_one()
        return fields.Datetime.context_timestamp(
            self.with_context(tz=self.timezone or 'UTC'),
            fields.Datetime.now(),
        )

    def _compute_next_run_datetime(self):
        self.ensure_one()
        active_schedules = self.schedule_ids.filtered('active')
        if not active_schedules or self.state != 'active' or not self.active:
            return False

        now_local = self._get_local_now()
        candidates = []
        for schedule in active_schedules:
            next_local = schedule.get_next_run_datetime(now_local)
            if next_local:
                candidates.append(next_local)
        if not candidates:
            return False
        return self._local_datetime_to_utc_string(min(candidates))

    def _local_datetime_to_utc_string(self, local_dt):
        self.ensure_one()
        if local_dt.tzinfo:
            utc_dt = local_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        else:
            tz = pytz.timezone(self.timezone or 'UTC')
            utc_dt = tz.localize(local_dt).astimezone(pytz.UTC).replace(tzinfo=None)
        return fields.Datetime.to_string(utc_dt)

    def _build_manual_backup_notification(self, history):
        self.ensure_one()
        return self.env['cb.backup.notification.service'].build_backup_client_action(self, history)

    def _should_notify_event(self, event):
        self.ensure_one()
        if event == 'success':
            return bool(self.notify_on_success)
        if event == 'partial':
            return bool(self.notify_on_partial)
        if event == 'failed':
            return bool(self.notify_on_failure)
        return False

    def _default_notification_user(self):
        user = self.env.user
        root = self.env.ref('base.user_root', raise_if_not_found=False)
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        if root and user.id == root.id and admin and admin.active:
            return admin
        return user

    def _get_notification_partners(self):
        self.ensure_one()
        root = self.env.ref('base.user_root', raise_if_not_found=False)
        allowed = (
            self.env.ref('cb_auto_backup_manager.group_cb_backup_administrator').all_user_ids
            | self.env.ref('cb_auto_backup_manager.group_cb_backup_operator').all_user_ids
        )
        users = (self.notification_user_ids & allowed).filtered('active')
        if root:
            users = users.filtered(lambda user: user.id != root.id)
        return users.mapped('partner_id').filtered('active')

    def _check_backup_execute_access(self):
        allowed_groups = (
            'cb_auto_backup_manager.group_cb_backup_administrator',
            'cb_auto_backup_manager.group_cb_backup_operator',
        )
        if not any(self.env.user.has_group(group) for group in allowed_groups):
            raise UserError(_('You are not allowed to execute backups.'))

    def _check_backup_admin_access(self):
        if not self.env.user.has_group('cb_auto_backup_manager.group_cb_backup_administrator'):
            raise UserError(_('Only Backup Administrators can change backup plan configuration or run cleanup.'))
