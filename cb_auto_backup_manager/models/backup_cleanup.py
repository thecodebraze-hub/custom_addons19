# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from odoo.addons.cb_auto_backup_manager.models.backup_utils import format_bytes


class CbBackupCleanupLog(models.Model):
    _name = 'cb.backup.cleanup.log'
    _description = 'Backup Cleanup Log'
    _order = 'cleanup_datetime desc, id desc'

    plan_id = fields.Many2one(
        'cb.backup.plan',
        string='Backup Plan',
        ondelete='set null',
        index=True,
    )
    storage_id = fields.Many2one(
        'cb.backup.storage',
        string='Storage Destination',
        ondelete='set null',
        index=True,
    )
    cleanup_datetime = fields.Datetime(
        string='Cleanup Date',
        default=fields.Datetime.now,
        index=True,
    )
    cutoff_datetime = fields.Datetime(
        string='Cutoff',
        help='Backup files strictly older than this datetime were eligible for deletion.',
    )
    files_scanned = fields.Integer(default=0)
    files_deleted = fields.Integer(default=0)
    files_skipped = fields.Integer(default=0)
    bytes_deleted = fields.Float(
        string='Bytes Deleted',
        default=0.0,
    )
    bytes_deleted_display = fields.Char(
        string='Space Freed',
        compute='_compute_bytes_deleted_display',
    )
    trigger_type = fields.Selection(
        selection=[
            ('manual', 'Manual'),
            ('after_backup', 'After Backup'),
            ('scheduled', 'Scheduled'),
        ],
        string='Trigger',
        default='scheduled',
    )
    status = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('partial', 'Partial'),
            ('failed', 'Failed'),
        ],
        required=True,
        default='success',
        index=True,
    )
    error_message = fields.Text()
    details = fields.Text(
        string='Details',
        help='Per-file skip and deletion notes without credentials.',
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

    @api.depends('plan_id.name', 'cleanup_datetime', 'storage_id.name')
    def _compute_display_name(self):
        for log in self:
            label = log.plan_id.name or log.storage_id.name or _('Cleanup Log')
            if log.cleanup_datetime:
                log.display_name = '%s — %s' % (
                    label,
                    fields.Datetime.to_string(log.cleanup_datetime),
                )
            else:
                log.display_name = label

    @api.depends('bytes_deleted')
    def _compute_bytes_deleted_display(self):
        for log in self:
            log.bytes_deleted_display = format_bytes(log.bytes_deleted) if log.bytes_deleted else '0 B'
