# -*- coding: utf-8 -*-
import hashlib
import hmac
import time
from uuid import uuid4

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    BackupError,
    sanitize_error_message,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)


class CbBackupStorage(models.Model):
    _name = 'cb.backup.storage'
    _description = 'Backup Storage Destination'
    _order = 'name, id'

    name = fields.Char(required=True)
    type = fields.Selection(
        selection=[
            ('local', 'Local Server'),
            ('sftp', 'SFTP Server'),
            ('google_drive', 'Google Drive'),
        ],
        required=True,
        default='local',
    )
    active = fields.Boolean(default=True)
    description = fields.Text()
    validation_status = fields.Selection(
        selection=[
            ('unknown', 'Not Tested'),
            ('valid', 'Connected'),
            ('invalid', 'Failed'),
            ('unsupported', 'Not Implemented'),
        ],
        string='Connection Status',
        default='unknown',
        readonly=True,
    )
    validation_message = fields.Char(
        string='Connection Message',
        readonly=True,
    )
    last_test_datetime = fields.Datetime(
        string='Last Tested',
        readonly=True,
    )
    connection_state = fields.Selection(
        selection=[
            ('ready', 'Ready'),
            ('not_tested', 'Not Tested'),
            ('failed', 'Failed'),
            ('disconnected', 'Disconnected'),
            ('unsupported', 'Unsupported'),
        ],
        string='Status',
        compute='_compute_connection_state',
    )

    local_path = fields.Char(
        string='Local Path',
        help='Absolute path on the Odoo server where backup ZIP files are stored.',
    )

    sftp_host = fields.Char(string='Host')
    sftp_port = fields.Integer(string='Port', default=22)
    sftp_username = fields.Char(string='Username')
    sftp_authentication_type = fields.Selection(
        selection=[
            ('password', 'Password'),
            ('private_key', 'Private Key'),
        ],
        string='Authentication',
        default='password',
    )
    sftp_password = fields.Char(
        string='Password',
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    sftp_private_key = fields.Text(
        string='Private Key',
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
        help='Paste the SSH private key. It is never written to backup files or logs.',
    )
    sftp_private_key_passphrase = fields.Char(
        string='Private Key Passphrase',
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    sftp_host_key = fields.Char(
        string='Host Key / Fingerprint',
        help=(
            'Expected SSH host fingerprint (SHA256 or MD5). '
            'Use Test Connection to discover the remote fingerprint, then save it here.'
        ),
    )
    sftp_remote_path = fields.Char(
        string='Remote Path',
        help='Absolute directory on the SFTP server, for example /backups/odoo.',
    )

    google_drive_account = fields.Char(
        string='Google Account',
        readonly=True,
        help='Filled automatically after a successful Google authorization.',
    )
    google_drive_folder = fields.Char(
        string='Google Drive Folder',
        default='Odoo Backups',
        help='Folder name created in Google Drive My Drive for this destination.',
    )
    google_drive_folder_id = fields.Char(
        string='Folder ID',
        readonly=True,
        copy=False,
    )
    google_drive_client_id = fields.Char(
        string='Client ID',
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    google_drive_client_secret = fields.Char(
        string='Client Secret',
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    google_drive_refresh_token = fields.Char(
        string='Refresh Token',
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    google_drive_access_token = fields.Char(
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    google_drive_token_expiry = fields.Datetime(
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    google_drive_oauth_nonce = fields.Char(
        copy=False,
        groups='cb_auto_backup_manager.group_cb_backup_administrator',
    )
    google_drive_redirect_uri = fields.Char(
        string='Redirect URI',
        compute='_compute_google_drive_redirect_uri',
        help='Copy this URL into the Google Cloud OAuth client as an authorized redirect URI.',
    )
    google_drive_connection_status = fields.Selection(
        selection=[
            ('disconnected', 'Disconnected'),
            ('connected', 'Connected'),
        ],
        string='Google Drive Status',
        default='disconnected',
        readonly=True,
    )

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        'A storage destination with this name already exists.',
    )

    @api.depends()
    def _compute_google_drive_redirect_uri(self):
        uri = self._google_drive_redirect_uri()
        for storage in self:
            storage.google_drive_redirect_uri = uri

    @api.model
    def _google_drive_redirect_uri(self):
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        return '%s/cb_auto_backup_manager/google_drive/oauth/callback' % base

    @api.depends('active', 'validation_status', 'type', 'google_drive_connection_status')
    def _compute_connection_state(self):
        for storage in self:
            if not storage.active:
                storage.connection_state = 'disconnected'
            elif storage.validation_status == 'valid':
                storage.connection_state = 'ready'
            elif storage.validation_status == 'invalid':
                storage.connection_state = 'failed'
            elif storage.validation_status == 'unsupported':
                storage.connection_state = 'unsupported'
            elif storage.type == 'google_drive' and storage.google_drive_connection_status == 'disconnected':
                storage.connection_state = 'disconnected'
            else:
                storage.connection_state = 'not_tested'

    @api.constrains(
        'name', 'local_path', 'type',
        'sftp_host', 'sftp_port', 'sftp_username', 'sftp_remote_path',
        'sftp_authentication_type',
        'google_drive_folder',
    )
    def _check_storage_configuration(self):
        for storage in self:
            if not (storage.name or '').strip():
                raise ValidationError(_('Storage destination name must not be empty.'))
            if storage.type == 'local' and not (storage.local_path or '').strip():
                raise ValidationError(_('Local storage requires a local path.'))
            if storage.type == 'sftp':
                if not (storage.sftp_host or '').strip():
                    raise ValidationError(_('SFTP host is required.'))
                port = storage.sftp_port or 0
                if port < 1 or port > 65535:
                    raise ValidationError(_('SFTP port must be between 1 and 65535.'))
                if not (storage.sftp_username or '').strip():
                    raise ValidationError(_('SFTP username is required.'))
                if not (storage.sftp_remote_path or '').strip():
                    raise ValidationError(_('SFTP remote path is required.'))
                remote = storage.sftp_remote_path.strip().replace('\\', '/')
                if not remote.startswith('/'):
                    raise ValidationError(_('SFTP remote path must be an absolute path.'))
                if any(part in ('.', '..') for part in remote.split('/') if part):
                    raise ValidationError(_('SFTP remote path must not contain parent references.'))
            if storage.type == 'google_drive':
                folder = (storage.google_drive_folder or '').strip() or 'Odoo Backups'
                if '/' in folder or '\\' in folder or folder in ('.', '..'):
                    raise ValidationError(_('Google Drive folder name must not contain path separators.'))

    def action_validate_storage(self):
        self.ensure_one()
        self._check_backup_admin_access()
        if self.type == 'local':
            return self._run_provider_validation(_('Local storage validated successfully.'))
        if self.type == 'sftp':
            return self.action_test_connection()
        if self.type == 'google_drive':
            return self.action_test_connection()
        raise UserError(_('Unsupported storage type.'))

    def action_test_connection(self):
        self.ensure_one()
        self._check_backup_admin_access()
        if self.type not in ('sftp', 'google_drive'):
            raise UserError(_('Test Connection is only available for SFTP and Google Drive destinations.'))
        return self._run_provider_validation(_('Storage connection successful.'))

    def _run_provider_validation(self, success_message):
        self.ensure_one()
        notifier = self.env['cb.backup.notification.service']
        provider = get_storage_provider(self)
        try:
            provider.validate()
            message = success_message or _('Storage connection successful.')
            self.write({
                'validation_status': 'valid',
                'validation_message': message,
                'last_test_datetime': fields.Datetime.now(),
            })
            return notifier.build_storage_client_action(True, storage=self)
        except (BackupError, Exception) as exc:
            message = sanitize_error_message(str(exc))
            self.write({
                'validation_status': 'invalid',
                'validation_message': message,
                'last_test_datetime': fields.Datetime.now(),
            })
            return notifier.build_storage_client_action(False, message, storage=self)

    def _validate_unsupported_storage(self, message):
        self.ensure_one()
        detail = sanitize_error_message(message)
        self.write({
            'validation_status': 'unsupported',
            'validation_message': detail,
            'last_test_datetime': fields.Datetime.now(),
        })
        action = self.env['cb.backup.notification.service'].build_storage_client_action(
            False, detail, storage=self,
        )
        action['params']['type'] = 'warning'
        action['params']['sticky'] = False
        return action

    def _check_backup_admin_access(self):
        if not self.env.user.has_group('cb_auto_backup_manager.group_cb_backup_administrator'):
            raise UserError(_('Only Backup Administrators can configure storage destinations.'))

    def _check_backup_execute_access(self):
        allowed_groups = (
            'cb_auto_backup_manager.group_cb_backup_administrator',
            'cb_auto_backup_manager.group_cb_backup_operator',
        )
        if not any(self.env.user.has_group(group) for group in allowed_groups):
            raise UserError(_('You are not allowed to execute backups.'))

    def action_connect_google_drive(self):
        self.ensure_one()
        self._check_backup_admin_access()
        if self.type != 'google_drive':
            raise UserError(_('Connect Google Drive is only available for Google Drive destinations.'))
        if not self.id:
            raise UserError(_('Save the storage destination before connecting Google Drive.'))
        nonce = uuid4().hex
        self.sudo().write({'google_drive_oauth_nonce': nonce})
        timestamp = str(int(time.time()))
        state = '%s.%s.%s.%s' % (self.id, self.env.uid, timestamp, nonce)
        signature = self._sign_google_oauth_state(state)
        redirect_uri = self._google_drive_redirect_uri()
        provider = get_storage_provider(self)
        try:
            url = provider.authorization_url(redirect_uri, '%s.%s' % (state, signature))
        except BackupError as exc:
            raise UserError(sanitize_error_message(str(exc))) from exc
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'self',
        }

    def action_disconnect_google_drive(self):
        self.ensure_one()
        self._check_backup_admin_access()
        self.sudo().write({
            'google_drive_refresh_token': False,
            'google_drive_access_token': False,
            'google_drive_token_expiry': False,
            'google_drive_oauth_nonce': False,
            'google_drive_folder_id': False,
            'google_drive_connection_status': 'disconnected',
            'validation_status': 'unknown',
            'validation_message': _('Google Drive disconnected.'),
        })
        return self.env['cb.backup.notification.service'].build_storage_client_action(
            True, _('Google Drive disconnected.'), storage=self,
        )

    @api.model
    def _sign_google_oauth_state(self, state):
        secret = (self.env['ir.config_parameter'].sudo().get_param('database.secret') or '').encode()
        return hmac.new(secret, state.encode(), hashlib.sha256).hexdigest()

    @api.model
    def _parse_google_oauth_state(self, raw_state):
        parts = (raw_state or '').split('.')
        if len(parts) != 5:
            raise UserError(_('Invalid Google authorization state.'))
        storage_id, uid, timestamp, nonce, signature = parts
        body = '%s.%s.%s.%s' % (storage_id, uid, timestamp, nonce)
        expected = self._sign_google_oauth_state(body)
        if not hmac.compare_digest(expected, signature):
            raise UserError(_('Invalid Google authorization state.'))
        try:
            issued = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise UserError(_('Invalid Google authorization state.')) from exc
        if abs(int(time.time()) - issued) > 600:
            raise UserError(_('Google authorization expired. Start Connect Google Drive again.'))
        return int(storage_id), int(uid), nonce

