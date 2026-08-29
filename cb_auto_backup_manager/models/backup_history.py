# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    format_bytes,
    format_duration,
    sanitize_error_message,
)


class CbBackupHistory(models.Model):
    _name = 'cb.backup.history'
    _description = 'Backup History'
    _order = 'backup_datetime desc, id desc'

    plan_id = fields.Many2one(
        'cb.backup.plan',
        string='Backup Plan',
        ondelete='set null',
        index=True,
    )
    schedule_id = fields.Many2one(
        'cb.backup.schedule',
        string='Schedule',
        ondelete='set null',
        readonly=True,
    )
    scheduled_occurrence = fields.Char(
        string='Schedule Occurrence',
        readonly=True,
        index=True,
        help='Logical identity of a scheduled run: plan + schedule + local date/time.',
    )
    trigger_type = fields.Selection(
        selection=[
            ('manual', 'Manual'),
            ('scheduled', 'Scheduled'),
        ],
        string='Trigger',
        readonly=True,
        default='manual',
    )
    database_name = fields.Char(
        string='Database',
        index=True,
    )
    backup_datetime = fields.Datetime(
        string='Backup Date',
        index=True,
    )
    start_datetime = fields.Datetime(
        string='Start Time',
    )
    end_datetime = fields.Datetime(
        string='End Time',
    )
    duration_seconds = fields.Float(
        string='Duration (Seconds)',
    )
    file_name = fields.Char(
        string='File Name',
    )
    file_path = fields.Char(
        string='File Path',
    )
    file_size = fields.Float(
        string='File Size (Bytes)',
        help='Backup file size in bytes.',
    )
    status = fields.Selection(
        selection=[
            ('running', 'Running'),
            ('success', 'Success'),
            ('partial', 'Partial'),
            ('failed', 'Failed'),
        ],
        string='Status',
        required=True,
        default='running',
        index=True,
    )
    error_message = fields.Text(
        string='Error Message',
    )
    checksum = fields.Char(
        string='Checksum',
    )
    encrypted = fields.Boolean(
        string='Encrypted',
        default=False,
        readonly=True,
    )
    encryption_method = fields.Selection(
        selection=[
            ('none', 'No Encryption'),
            ('aes256', 'AES-256'),
        ],
        string='Encryption Method',
        default='none',
        readonly=True,
    )
    active = fields.Boolean(default=True)
    file_deleted = fields.Boolean(
        string='File Deleted',
        default=False,
        readonly=True,
        help='True when the backup ZIP was removed by the retention policy.',
    )
    file_deleted_datetime = fields.Datetime(
        string='Deleted Date',
        readonly=True,
    )
    file_storage_status = fields.Selection(
        selection=[
            ('available', 'Available'),
            ('deleted', 'Deleted by Retention'),
            ('missing', 'Missing'),
            ('none', 'Not stored'),
        ],
        string='File Status',
        compute='_compute_file_storage_status',
    )
    file_size_display = fields.Char(
        string='Size',
        compute='_compute_file_size_display',
    )
    duration_display = fields.Char(
        string='Duration',
        compute='_compute_duration_display',
    )
    error_summary = fields.Char(
        string='Error Summary',
        compute='_compute_error_summary',
    )
    storage_ids = fields.Many2many(
        'cb.backup.storage',
        string='Storage Destinations',
        compute='_compute_storage_ids',
        search='_search_storage_ids',
    )
    destination_result_ids = fields.One2many(
        'cb.backup.history.destination',
        'history_id',
        string='Destination Results',
        readonly=True,
    )
    destination_summary = fields.Char(
        string='Destination Result',
        compute='_compute_destination_summary',
    )
    notification_key = fields.Char(
        string='Notification Key',
        index=True,
        copy=False,
    )
    notification_sent = fields.Boolean(
        string='Notification Sent',
        default=False,
        copy=False,
    )
    last_verified_datetime = fields.Datetime(
        string='Last Verified',
        readonly=True,
    )
    verification_status = fields.Selection(
        selection=[
            ('never', 'Never Tested'),
            ('verified', 'Verified'),
            ('failed', 'Failed'),
        ],
        string='Verification',
        default='never',
        readonly=True,
    )
    last_restore_test_datetime = fields.Datetime(
        string='Last Test Restore',
        readonly=True,
    )
    restore_test_status = fields.Selection(
        selection=[
            ('never', 'Never Tested'),
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('warning', 'Warning'),
        ],
        string='Test Restore',
        default='never',
        readonly=True,
    )
    restore_log_ids = fields.One2many(
        'cb.backup.restore.log',
        'history_id',
        string='Restore Logs',
        readonly=True,
    )

    def action_verify_backup(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Verify Backup'),
            'res_model': 'cb.backup.restore.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_history_id': self.id,
                'default_restore_mode': 'verify_only',
            },
        }

    def action_test_restore(self):
        self.ensure_one()
        if not self.env.user.has_group(
            'cb_auto_backup_manager.group_cb_backup_administrator'
        ):
            raise UserError(_('Only Backup Administrators can run a temporary restore test.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Test Restore'),
            'res_model': 'cb.backup.restore.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_history_id': self.id,
                'default_restore_mode': 'temporary_restore',
            },
        }

    @api.depends('file_name', 'database_name', 'backup_datetime')
    def _compute_display_name(self):
        for history in self:
            if history.file_name:
                history.display_name = history.file_name
            elif history.backup_datetime:
                stamp = fields.Datetime.to_string(history.backup_datetime)
                db = history.database_name or ''
                history.display_name = '%s — %s' % (db, stamp) if db else stamp
            else:
                history.display_name = history.database_name or _('Backup History')

    @api.depends(
        'file_deleted',
        'status',
        'file_path',
        'destination_result_ids.status',
        'destination_result_ids.file_path',
        'destination_result_ids.file_deleted',
    )
    def _compute_file_storage_status(self):
        for history in self:
            if history.file_deleted:
                history.file_storage_status = 'deleted'
                continue
            dests = history.destination_result_ids
            available_dests = dests.filtered(
                lambda line: line.status == 'success' and not line.file_deleted and line.file_path
            )
            if history.status in ('success', 'partial') and (history.file_path or available_dests):
                history.file_storage_status = 'available'
            elif history.status in ('success', 'partial'):
                history.file_storage_status = 'missing'
            else:
                history.file_storage_status = 'none'

    @api.depends('file_size')
    def _compute_file_size_display(self):
        for history in self:
            history.file_size_display = format_bytes(history.file_size) if history.file_size else False

    @api.depends('duration_seconds')
    def _compute_duration_display(self):
        for history in self:
            history.duration_display = (
                format_duration(history.duration_seconds)
                if history.duration_seconds else False
            )

    @api.depends('error_message')
    def _compute_error_summary(self):
        for history in self:
            message = sanitize_error_message(history.error_message or '')
            if not history.error_message:
                history.error_summary = False
                continue
            first_line = message.strip().splitlines()[0] if message.strip() else ''
            history.error_summary = (first_line[:120] + '…') if len(first_line) > 120 else first_line

    @api.depends('destination_result_ids.storage_id')
    def _compute_storage_ids(self):
        for history in self:
            history.storage_ids = history.destination_result_ids.mapped('storage_id')

    def _search_storage_ids(self, operator, value):
        destinations = self.env['cb.backup.history.destination'].search([
            ('storage_id', operator, value),
        ])
        return [('id', 'in', destinations.mapped('history_id').ids)]

    @api.depends(
        'destination_result_ids.storage_name',
        'destination_result_ids.storage_type',
        'destination_result_ids.status',
    )
    def _compute_destination_summary(self):
        type_labels = dict(self.env['cb.backup.history.destination']._fields['storage_type'].selection)
        status_labels = dict(self.env['cb.backup.history.destination']._fields['status'].selection)
        for history in self:
            parts = []
            for line in history.destination_result_ids:
                name = line.storage_name or type_labels.get(line.storage_type) or line.storage_type
                status = status_labels.get(line.status, line.status)
                parts.append('%s — %s' % (name, status))
            history.destination_summary = ' | '.join(parts) if parts else False


class CbBackupHistoryDestination(models.Model):
    _name = 'cb.backup.history.destination'
    _description = 'Backup History Destination Result'
    _order = 'id'

    history_id = fields.Many2one(
        'cb.backup.history',
        string='Backup History',
        required=True,
        ondelete='cascade',
        index=True,
    )
    storage_id = fields.Many2one(
        'cb.backup.storage',
        string='Storage Destination',
        ondelete='set null',
    )
    storage_name = fields.Char(
        string='Destination Name',
    )
    storage_type = fields.Selection(
        selection=[
            ('local', 'Local Server'),
            ('sftp', 'SFTP Server'),
            ('google_drive', 'Google Drive'),
        ],
        string='Destination Type',
    )
    status = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('not_implemented', 'Not Implemented'),
        ],
        required=True,
    )
    file_path = fields.Char(
        string='Stored Path',
    )
    file_size = fields.Float(
        string='File Size (Bytes)',
    )
    file_size_display = fields.Char(
        string='Size',
        compute='_compute_file_size_display',
    )
    error_message = fields.Text(
        string='Error Message',
    )
    started = fields.Datetime(
        string='Started',
        readonly=True,
    )
    completed = fields.Datetime(
        string='Completed',
        readonly=True,
    )
    file_deleted = fields.Boolean(
        string='File Deleted',
        default=False,
        readonly=True,
    )
    file_deleted_datetime = fields.Datetime(
        string='Deleted Date',
        readonly=True,
    )

    @api.depends('storage_name', 'storage_type', 'status')
    def _compute_display_name(self):
        type_labels = dict(self._fields['storage_type'].selection)
        status_labels = dict(self._fields['status'].selection)
        for line in self:
            name = line.storage_name or type_labels.get(line.storage_type) or _('Destination')
            status = status_labels.get(line.status, line.status)
            line.display_name = '%s (%s)' % (name, status)

    @api.depends('file_size')
    def _compute_file_size_display(self):
        for line in self:
            line.file_size_display = format_bytes(line.file_size) if line.file_size else False

