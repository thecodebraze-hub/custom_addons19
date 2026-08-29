# -*- coding: utf-8 -*-
import logging

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.cb_auto_backup_manager.models.backup_utils import sanitize_error_message
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)

_logger = logging.getLogger(__name__)


class CbBackupGoogleDriveController(http.Controller):

    @http.route(
        '/cb_auto_backup_manager/google_drive/oauth/callback',
        type='http',
        auth='public',
        csrf=False,
        methods=['GET'],
    )
    def google_drive_oauth_callback(self, **kwargs):
        error = kwargs.get('error')
        if error:
            _logger.warning('Google Drive OAuth returned an error code without token details.')
            return request.redirect('/web#action=cb_auto_backup_manager.action_cb_backup_storage')

        state = kwargs.get('state')
        code = kwargs.get('code')
        Storage = request.env['cb.backup.storage'].sudo()
        try:
            storage_id, _uid, nonce = Storage._parse_google_oauth_state(state)
        except (UserError, ValueError):
            return self._oauth_error_redirect(_('Google authorization state is invalid or expired.'))

        storage = Storage.browse(storage_id)
        if not storage.exists() or storage.type != 'google_drive':
            return self._oauth_error_redirect(_('Storage destination was not found.'))
        if not nonce or nonce != (storage.google_drive_oauth_nonce or ''):
            return self._oauth_error_redirect(_('Google authorization state is invalid or expired.'))
        if not code:
            return self._oauth_error_redirect(_('Google did not return an authorization code.'))

        try:
            provider = get_storage_provider(storage)
            provider.exchange_authorization_code(code, Storage._google_drive_redirect_uri())
            storage.write({
                'google_drive_oauth_nonce': False,
                'google_drive_connection_status': 'connected',
                'validation_status': 'valid',
                'validation_message': _('Google Drive connected successfully.'),
            })
        except Exception as exc:
            storage.write({
                'google_drive_oauth_nonce': False,
                'google_drive_connection_status': 'disconnected',
                'validation_status': 'invalid',
                'validation_message': sanitize_error_message(str(exc)),
            })
            _logger.warning('Google Drive OAuth exchange failed for storage %s.', storage.id)
            return self._oauth_form_redirect(storage.id)

        return self._oauth_form_redirect(storage.id)

    def _oauth_form_redirect(self, storage_id):
        return request.redirect(
            '/web#id=%s&model=cb.backup.storage&view_type=form' % int(storage_id)
        )

    def _oauth_error_redirect(self, _message):
        return request.redirect('/web#action=cb_auto_backup_manager.action_cb_backup_storage')
