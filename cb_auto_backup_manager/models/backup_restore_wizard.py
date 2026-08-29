# -*- coding: utf-8 -*-
from datetime import datetime

import odoo.release
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    compare_odoo_versions,
    generate_temp_restore_database_name,
    read_backup_manifest,
)


class CbBackupRestoreWizard(models.TransientModel):
    _name = 'cb.backup.restore.wizard'
    _description = 'Backup Restore Wizard'
    _rec_name = 'name'

    name = fields.Char(readonly=True)
    history_id = fields.Many2one(
        'cb.backup.history',
        string='Backup History',
        required=True,
        ondelete='cascade',
    )
    backup_file = fields.Char(
        string='Backup',
        readonly=True,
    )
    database_name = fields.Char(
        string='Database',
        readonly=True,
    )
    backup_datetime = fields.Datetime(
        string='Backup Date',
        readonly=True,
    )
    checksum = fields.Char(
        readonly=True,
    )
    checksum_status = fields.Char(
        string='Checksum',
        readonly=True,
    )
    odoo_version_backup = fields.Char(
        string='Odoo Version',
        readonly=True,
    )
    odoo_version_current = fields.Char(
        readonly=True,
    )
    version_warning = fields.Char(
        readonly=True,
    )
    acknowledge_version_warning = fields.Boolean(
        string='I understand this backup is from a different Odoo major version',
    )
    restore_mode = fields.Selection(
        selection=[
            ('verify_only', 'Verify Only'),
            ('temporary_restore', 'Temporary Restore'),
        ],
        string='Restore Mode',
        required=True,
        default='verify_only',
    )
    target_database_name = fields.Char(
        string='Target Database',
        readonly=True,
    )
    storage_id = fields.Many2one(
        'cb.backup.storage',
        string='Source Destination',
    )
    available_storage_ids = fields.Many2many(
        'cb.backup.storage',
        compute='_compute_available_storage_ids',
    )
    verify_database = fields.Boolean(
        default=True,
    )
    verify_filestore = fields.Boolean(
        default=True,
    )
    cleanup_after_test = fields.Boolean(
        string='Cleanup After Test',
        default=True,
    )
    result = fields.Char(
        readonly=True,
    )
    error_message = fields.Text(
        readonly=True,
    )
    can_test_restore = fields.Boolean(
        compute='_compute_can_test_restore',
    )
    encrypted = fields.Boolean(readonly=True)
    encryption_method = fields.Char(readonly=True)
    encryption_secret = fields.Char(
        string='Encryption Secret',
        copy=False,
    )

    @api.depends('history_id')
    def _compute_available_storage_ids(self):
        for wizard in self:
            wizard.available_storage_ids = wizard.history_id.destination_result_ids.filtered(
                lambda line: line.status == 'success' and not line.file_deleted and line.storage_id
            ).mapped('storage_id')

    @api.depends_context('uid')
    def _compute_can_test_restore(self):
        is_admin = self.env.user.has_group(
            'cb_auto_backup_manager.group_cb_backup_administrator'
        )
        for wizard in self:
            wizard.can_test_restore = is_admin

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        history = self.env['cb.backup.history'].browse(
            values.get('history_id') or self.env.context.get('default_history_id')
        )
        if not history:
            return values
        values['name'] = history.file_name or _('Backup Restore')
        values['history_id'] = history.id
        values['backup_file'] = history.file_name
        values['database_name'] = history.database_name
        values['backup_datetime'] = history.backup_datetime
        values['checksum'] = history.checksum
        values['checksum_status'] = _('stored') if history.checksum else _('not stored')
        values['odoo_version_current'] = odoo.release.version
        values['restore_mode'] = self.env.context.get('default_restore_mode') or 'verify_only'
        values['encrypted'] = bool(history.encrypted)
        values['encryption_method'] = (
            dict(history._fields['encryption_method'].selection).get(
                history.encryption_method or 'none',
                history.encryption_method,
            )
            if history.encrypted else _('Not encrypted')
        )
        stamp = fields.Datetime.to_datetime(history.backup_datetime) if history.backup_datetime else datetime.utcnow()
        values['target_database_name'] = generate_temp_restore_database_name(
            history.database_name or 'restore',
            stamp,
        )
        local_path = history.file_path
        manifest = read_backup_manifest(local_path) if local_path else None
        backup_version = (manifest or {}).get('odoo_version') or ''
        values['odoo_version_backup'] = backup_version or _('Read from backup during verification')
        _compatible, _major, warning = compare_odoo_versions(
            backup_version,
            odoo.release.version,
        )
        values['version_warning'] = warning or False
        lines = history.destination_result_ids.filtered(
            lambda line: line.status == 'success' and not line.file_deleted and line.storage_id
        )
        preferred = lines.filtered(lambda line: line.storage_type == 'local') or lines
        if preferred:
            values['storage_id'] = preferred[:1].storage_id.id
        return values

    def action_verify(self):
        self.ensure_one()
        self._check_verify_access()
        result = self.env['cb.backup.restore.service'].verify_backup(
            self.history_id,
            storage=self.storage_id,
            encryption_secret=self.encryption_secret,
        )
        return self._finish(result)

    def action_test_restore(self):
        self.ensure_one()
        self._check_restore_access()
        if self.version_warning and 'different Odoo major version' in (self.version_warning or '') and not self.acknowledge_version_warning:
            raise UserError(self.version_warning)
        result = self.env['cb.backup.restore.service'].test_restore(
            self.history_id,
            storage=self.storage_id,
            verify_database=self.verify_database,
            verify_filestore=self.verify_filestore,
            cleanup_after_test=self.cleanup_after_test,
            acknowledge_version_warning=self.acknowledge_version_warning,
            target_database_name=self.target_database_name,
            encryption_secret=self.encryption_secret,
        )
        return self._finish(result)

    def _finish(self, result):
        self.write({
            'result': result.get('message'),
            'error_message': result.get('error_message') or False,
            'checksum_status': _('verified') if result.get('checksum_verified') else _('failed'),
            'encryption_secret': False,
        })
        severity = 'success'
        if result.get('status') == 'warning':
            severity = 'warning'
        elif not result.get('success'):
            severity = 'danger'
        return self.env['cb.backup.notification.service'].build_restore_client_action(
            result.get('message'),
            severity,
            detail=result.get('error_message') if not result.get('success') else '',
            action_record=result.get('log'),
        )

    def _check_verify_access(self):
        allowed = (
            'cb_auto_backup_manager.group_cb_backup_administrator',
            'cb_auto_backup_manager.group_cb_backup_operator',
        )
        if not any(self.env.user.has_group(group) for group in allowed):
            raise UserError(_('You are not allowed to verify backups.'))

    def _check_restore_access(self):
        if not self.env.user.has_group('cb_auto_backup_manager.group_cb_backup_administrator'):
            raise UserError(_('Only Backup Administrators can run a temporary restore test.'))
