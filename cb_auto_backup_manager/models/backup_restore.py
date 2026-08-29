# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from odoo.addons.cb_auto_backup_manager.models.backup_utils import format_duration


class CbBackupRestoreLog(models.Model):
    _name = 'cb.backup.restore.log'
    _description = 'Backup Restore Log'
    _order = 'restore_datetime desc, id desc'

    history_id = fields.Many2one(
        'cb.backup.history',
        string='Backup History',
        ondelete='set null',
        index=True,
    )
    restore_datetime = fields.Datetime(
        string='Restore Date',
        default=fields.Datetime.now,
        index=True,
    )
    restore_mode = fields.Selection(
        selection=[
            ('verify_only', 'Verify Only'),
            ('temporary_restore', 'Temporary Restore'),
        ],
        required=True,
        default='verify_only',
        index=True,
    )
    target_database = fields.Char(
        string='Target Database',
    )
    created_database = fields.Boolean(
        default=False,
        help='True when this restore test created the target database.',
    )
    status = fields.Selection(
        selection=[
            ('running', 'Running'),
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('warning', 'Warning'),
        ],
        required=True,
        default='running',
        index=True,
    )
    duration_seconds = fields.Float()
    duration_display = fields.Char(
        string='Duration',
        compute='_compute_duration_display',
    )
    database_verified = fields.Boolean()
    filestore_verified = fields.Boolean()
    checksum_verified = fields.Boolean()
    odoo_version_compatible = fields.Boolean()
    cleanup_status = fields.Selection(
        selection=[
            ('skipped', 'Skipped'),
            ('cleaned', 'Cleaned'),
            ('failed', 'Failed'),
            ('pending', 'Pending'),
        ],
        default='skipped',
    )
    error_message = fields.Text()
    result_message = fields.Char()
    backup_odoo_version = fields.Char()
    current_odoo_version = fields.Char()
    storage_id = fields.Many2one(
        'cb.backup.storage',
        string='Storage Destination',
        ondelete='set null',
    )

    @api.depends('restore_mode', 'restore_datetime', 'target_database', 'history_id.file_name')
    def _compute_display_name(self):
        mode_labels = dict(self._fields['restore_mode'].selection)
        for log in self:
            mode = mode_labels.get(log.restore_mode, log.restore_mode)
            if log.history_id.file_name:
                log.display_name = '%s — %s' % (mode, log.history_id.file_name)
            elif log.restore_datetime:
                log.display_name = '%s — %s' % (
                    mode,
                    fields.Datetime.to_string(log.restore_datetime),
                )
            else:
                log.display_name = mode

    @api.depends('duration_seconds')
    def _compute_duration_display(self):
        for log in self:
            log.duration_display = (
                format_duration(log.duration_seconds) if log.duration_seconds else False
            )
