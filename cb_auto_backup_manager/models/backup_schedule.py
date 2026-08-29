# -*- coding: utf-8 -*-
from datetime import timedelta
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

WEEKDAY_SELECTION = [
    ('monday', 'Monday'),
    ('tuesday', 'Tuesday'),
    ('wednesday', 'Wednesday'),
    ('thursday', 'Thursday'),
    ('friday', 'Friday'),
    ('saturday', 'Saturday'),
    ('sunday', 'Sunday'),
]

WEEKDAY_TO_INDEX = {
    'monday': 0,
    'tuesday': 1,
    'wednesday': 2,
    'thursday': 3,
    'friday': 4,
    'saturday': 5,
    'sunday': 6,
}


class CbBackupSchedule(models.Model):
    _name = 'cb.backup.schedule'
    _description = 'Backup Schedule'
    _order = 'plan_id, frequency, time_hour, time_minute, id'

    plan_id = fields.Many2one(
        'cb.backup.plan',
        string='Backup Plan',
        required=True,
        ondelete='cascade',
        index=True,
    )
    frequency = fields.Selection(
        selection=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
        ],
        required=True,
        default='daily',
    )
    weekday = fields.Selection(
        selection=WEEKDAY_SELECTION,
        string='Weekday',
    )
    month_day = fields.Integer(
        string='Day of Month',
        help='Day of the month (1-31) for monthly schedules. Leave empty for daily and weekly.',
    )
    time_hour = fields.Integer(
        string='Hour',
        required=True,
        default=0,
        help='Hour of the day (0-23).',
    )
    time_minute = fields.Integer(
        string='Minute',
        required=True,
        default=0,
        help='Minute of the hour (0-59).',
    )
    active = fields.Boolean(default=True)
    last_run_datetime = fields.Datetime(
        string='Last Run',
        readonly=True,
        help='Last time this schedule triggered a backup.',
    )
    time_display = fields.Char(
        string='Time',
        compute='_compute_time_display',
        inverse='_inverse_time_display',
        help='Backup time in HH:MM (24-hour).',
    )
    line_number = fields.Integer(
        string='#',
        compute='_compute_line_number',
    )

    _time_hour_valid = models.Constraint(
        'CHECK(time_hour >= 0 AND time_hour <= 23)',
        'Hour must be between 0 and 23.',
    )
    _time_minute_valid = models.Constraint(
        'CHECK(time_minute >= 0 AND time_minute <= 59)',
        'Minute must be between 0 and 59.',
    )
    _month_day_valid = models.Constraint(
        'CHECK(month_day IS NULL OR month_day = 0 OR (month_day >= 1 AND month_day <= 31))',
        'Day of month must be between 1 and 31.',
    )

    @api.depends('frequency', 'weekday', 'month_day', 'time_hour', 'time_minute')
    def _compute_display_name(self):
        freq_labels = dict(self._fields['frequency'].selection)
        weekday_labels = dict(WEEKDAY_SELECTION)
        for schedule in self:
            parts = [freq_labels.get(schedule.frequency, schedule.frequency)]
            if schedule.frequency == 'weekly' and schedule.weekday:
                parts.append(weekday_labels.get(schedule.weekday, schedule.weekday))
            if schedule.frequency == 'monthly' and schedule.month_day:
                parts.append(_('Day %s') % schedule.month_day)
            parts.append('%02d:%02d' % (schedule.time_hour, schedule.time_minute))
            schedule.display_name = ' '.join(parts)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Odoo 19 Integer stores False as 0; omit empty month_day so PostgreSQL keeps NULL.
            if not vals.get('month_day'):
                vals.pop('month_day', None)
        return super().create(vals_list)

    @api.depends('time_hour', 'time_minute')
    def _compute_time_display(self):
        for schedule in self:
            schedule.time_display = '%02d:%02d' % (schedule.time_hour, schedule.time_minute)

    def _inverse_time_display(self):
        for schedule in self:
            hour, minute = parse_schedule_time(schedule.time_display)
            schedule.time_hour = hour
            schedule.time_minute = minute

    @api.depends(
        'plan_id',
        'plan_id.schedule_ids',
        'frequency',
        'weekday',
        'month_day',
        'time_hour',
        'time_minute',
    )
    def _compute_line_number(self):
        frequency_order = {'daily': 0, 'weekly': 1, 'monthly': 2}
        numbered = self.browse()
        for plan in self.mapped('plan_id'):
            lines = plan.schedule_ids.sorted(key=lambda schedule: (
                frequency_order.get(schedule.frequency, 9),
                schedule.weekday or '',
                schedule.month_day or 0,
                schedule.time_hour,
                schedule.time_minute,
                schedule.id or 0,
            ))
            for index, schedule in enumerate(lines, start=1):
                if schedule in self:
                    schedule.line_number = index
                    numbered |= schedule
        for schedule in self - numbered:
            schedule.line_number = 0

    @api.constrains('frequency', 'weekday', 'month_day')
    def _check_frequency_fields(self):
        for schedule in self:
            if schedule.frequency == 'weekly' and not schedule.weekday:
                raise ValidationError(
                    _('Weekly schedules must specify a weekday.')
                )
            if schedule.frequency == 'monthly' and not schedule.month_day:
                raise ValidationError(
                    _('Monthly schedules must specify a day of the month (1-31).')
                )
            if schedule.frequency == 'daily':
                if schedule.weekday:
                    raise ValidationError(
                        _('Daily schedules must not specify a weekday.')
                    )
                if schedule.month_day:
                    raise ValidationError(
                        _('Daily schedules must not specify a day of the month.')
                    )

    @api.constrains(
        'plan_id', 'frequency', 'weekday', 'month_day',
        'time_hour', 'time_minute', 'active',
    )
    def _check_duplicate_schedule(self):
        for schedule in self.filtered('active'):
            if not schedule.plan_id:
                continue
            others = self.search([
                ('id', '!=', schedule.id),
                ('plan_id', '=', schedule.plan_id.id),
                ('active', '=', True),
                ('time_hour', '=', schedule.time_hour),
                ('time_minute', '=', schedule.time_minute),
            ])
            for other in others:
                same_slot = (
                    schedule.frequency == 'daily'
                    or other.frequency == 'daily'
                    or (
                        schedule.frequency == 'weekly'
                        and other.frequency == 'weekly'
                        and schedule.weekday == other.weekday
                    )
                    or (
                        schedule.frequency == 'monthly'
                        and other.frequency == 'monthly'
                        and schedule.month_day == other.month_day
                    )
                )
                if same_slot:
                    raise ValidationError(
                        _('This backup plan already has an active schedule at %s. Duplicate times are not allowed.')
                        % schedule.time_display
                    )

    def is_due(self, now_local):
        self.ensure_one()
        if not self.active or not self.plan_id.active or self.plan_id.state != 'active':
            return False
        if now_local.hour != self.time_hour or now_local.minute != self.time_minute:
            return False
        if self.frequency == 'weekly':
            if now_local.weekday() != WEEKDAY_TO_INDEX[self.weekday]:
                return False
        elif self.frequency == 'monthly':
            if now_local.day != self.month_day:
                return False
        if self._already_ran_this_slot(now_local):
            return False
        if self._occurrence_already_processed(now_local):
            return False
        return True

    def get_next_run_datetime(self, now_local):
        self.ensure_one()
        candidate = now_local.replace(
            hour=self.time_hour,
            minute=self.time_minute,
            second=0,
            microsecond=0,
        )
        for _unused in range(366):
            if self._matches_schedule(candidate):
                if candidate >= now_local.replace(second=0, microsecond=0):
                    return candidate
            candidate += timedelta(days=1)
        return False

    def _matches_schedule(self, local_dt):
        if self.frequency == 'daily':
            return True
        if self.frequency == 'weekly':
            return local_dt.weekday() == WEEKDAY_TO_INDEX[self.weekday]
        if self.frequency == 'monthly':
            return local_dt.day == self.month_day
        return False

    def _already_ran_this_slot(self, now_local):
        self.ensure_one()
        if not self.last_run_datetime:
            return False
        last_local = fields.Datetime.context_timestamp(
            self.plan_id.with_context(tz=self.plan_id.timezone or 'UTC'),
            self.last_run_datetime,
        )
        return self._slot_key(last_local) == self._slot_key(now_local)

    def _slot_key(self, local_dt):
        self.ensure_one()
        time_part = '%02d:%02d' % (self.time_hour, self.time_minute)
        if self.frequency == 'daily':
            return '%s %s' % (local_dt.date(), time_part)
        if self.frequency == 'weekly':
            iso_year, iso_week, _iso_weekday = local_dt.isocalendar()
            return '%s-W%s %s' % (iso_year, iso_week, time_part)
        if self.frequency == 'monthly':
            return '%s-%02d-%02d %s' % (local_dt.year, local_dt.month, self.month_day, time_part)
        return '%s %s' % (local_dt, time_part)

    def get_occurrence_key(self, now_local):
        """Unique identity for one scheduled run: plan + schedule + local slot datetime."""
        self.ensure_one()
        slot = now_local.replace(
            hour=self.time_hour,
            minute=self.time_minute,
            second=0,
            microsecond=0,
        )
        return '%s:%s:%s' % (
            self.plan_id.id,
            self.id,
            slot.strftime('%Y-%m-%d %H:%M'),
        )

    def _occurrence_already_processed(self, now_local):
        self.ensure_one()
        if not self.id or not self.plan_id:
            return False
        key = self.get_occurrence_key(now_local)
        return bool(self.env['cb.backup.history'].search_count([
            ('plan_id', '=', self.plan_id.id),
            ('schedule_id', '=', self.id),
            ('scheduled_occurrence', '=', key),
            ('trigger_type', '=', 'scheduled'),
            ('status', 'in', ('success', 'partial', 'failed', 'running')),
        ]))


def parse_schedule_time(value):
    """Parse HH:MM (24-hour) into hour and minute integers."""
    raw = (value or '').strip()
    if not raw:
        raise ValidationError(_('Backup time is required. Use HH:MM, for example 06:00.'))
    match = re.fullmatch(r'(\d{1,2})(?::(\d{1,2}))?', raw)
    if not match:
        raise ValidationError(_('Time must be in HH:MM format, for example 06:00 or 14:30.'))
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour < 0 or hour > 23:
        raise ValidationError(_('Hour must be between 0 and 23.'))
    if minute < 0 or minute > 59:
        raise ValidationError(_('Minute must be between 0 and 59.'))
    return hour, minute
