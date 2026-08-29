# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools.misc import html_escape

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    format_bytes,
    sanitize_error_message,
)

_logger = logging.getLogger(__name__)


class CbBackupNotificationService(models.AbstractModel):
    _name = 'cb.backup.notification.service'
    _description = 'Backup Notification Service'

    @api.model
    def notify_backup(self, plan, history, trigger='manual'):
        """Send Discuss/inbox notifications for a finished backup."""
        plan.ensure_one()
        history.ensure_one()
        event = history.status if history.status in ('success', 'partial', 'failed') else 'failed'
        if not plan._should_notify_event(event):
            return self.env['mail.message']
        notification_key = self._backup_notification_key(history)
        if self._backup_already_notified(notification_key, history):
            return self.env['mail.message']
        title, body, _severity = self._backup_content(plan, history)
        message = self._send_inbox(
            plan,
            title,
            body,
            model='cb.backup.history',
            res_id=history.id,
        )
        history.write({
            'notification_key': notification_key,
            'notification_sent': bool(message),
        })
        return message

    @api.model
    def notify_cleanup(self, plan, logs, trigger='manual'):
        """Send Discuss/inbox notifications for retention cleanup."""
        plan.ensure_one()
        if not logs:
            return self.env['mail.message']
        outcome = self._cleanup_outcome(logs)
        if outcome == 'success':
            return self.env['mail.message']
        if not plan.notify_on_cleanup_failure:
            return self.env['mail.message']
        notification_key = self._cleanup_notification_key(plan, logs, trigger)
        if self._cleanup_already_notified(notification_key):
            return self.env['mail.message']
        title, body, _severity = self._cleanup_content(plan, logs)
        message = self._send_inbox(
            plan,
            title,
            body,
            model='cb.backup.cleanup.log',
            res_id=logs[:1].id,
        )
        logs.write({
            'notification_key': notification_key,
            'notification_sent': bool(message),
        })
        return message

    @api.model
    def notify_cleanup_error(self, plan, error_message, trigger='scheduled'):
        """Inbox notification when cleanup raises before destination logs exist."""
        plan.ensure_one()
        if not plan.notify_on_cleanup_failure:
            return self.env['mail.message']
        title = _('Backup Cleanup Failed')
        body = self._html_sections([
            (_('Summary'), _('Backup cleanup failed.')),
            (_('Plan'), plan.name),
            (_('Reason'), sanitize_error_message(error_message)),
        ])
        return self._send_inbox(
            plan,
            title,
            body,
            model='cb.backup.plan',
            res_id=plan.id,
        )

    @api.model
    def build_backup_client_action(self, plan, history):
        """Immediate toast for Backup Now."""
        title, message, severity = self._backup_content(plan, history, html=False)
        return self._client_notification(
            title,
            message,
            severity,
            sticky=severity in ('warning', 'danger'),
            action_record=history,
        )

    @api.model
    def build_cleanup_client_action(self, plan, logs):
        """Immediate toast for Cleanup Now."""
        title, message, severity = self._cleanup_content(plan, logs, html=False)
        return self._client_notification(
            title,
            message,
            severity,
            sticky=severity == 'danger',
        )

    @api.model
    def build_restore_client_action(self, message, severity='success', detail='', action_record=False):
        """Immediate toast for backup verification and test restore."""
        text = sanitize_error_message(message or '')
        if detail and severity == 'danger':
            extra = sanitize_error_message(detail)
            if extra:
                text = '%s\n%s' % (text, extra)
        return self._client_notification(
            _('Backup Restore'),
            text,
            severity,
            sticky=severity in ('warning', 'danger'),
            action_record=action_record,
        )

    @api.model
    def build_storage_client_action(self, success, detail_message='', storage=None):
        """Immediate toast for Test Connection / Validate Storage.

        When *storage* is provided, reload that form so Status / Connection
        Status fields refresh after the toast (display_notification alone
        does not reload the current form).
        """
        if success:
            action = self._client_notification(
                _('Storage Connection'),
                detail_message or _('Storage connection successful.'),
                'success',
            )
        else:
            detail = sanitize_error_message(detail_message) if detail_message else ''
            message = _('Storage connection failed.')
            if detail:
                message = '%s\n%s' % (message, detail)
            action = self._client_notification(
                _('Storage Connection'),
                message,
                'danger',
                sticky=True,
            )
        if storage:
            storage.ensure_one()
            action['params']['next'] = {
                'type': 'ir.actions.act_window',
                'res_model': storage._name,
                'res_id': storage.id,
                'views': [(False, 'form')],
                'view_mode': 'form',
                'target': 'current',
            }
        return action

    def _backup_content(self, plan, history, html=True):
        status = history.status
        dest_text = history.destination_summary or _('None')
        reason = sanitize_error_message(history.error_message or '') if history.error_message else ''
        unavailable = history.destination_result_ids.filtered(
            lambda line: line.status in ('failed', 'not_implemented')
        )
        if status == 'success':
            title = _('Backup Successful')
            severity = 'success'
            intro = (
                _('Encrypted backup completed successfully.')
                if history.encrypted else _('Backup completed successfully.')
            )
        elif status == 'partial':
            title = _('Backup Partially Completed')
            severity = 'warning'
            intro = _('Backup created successfully, but one storage destination failed.')
            if unavailable:
                intro = (
                    _('Encrypted backup completed successfully.')
                    if history.encrypted else _('Backup created successfully.')
                )
        else:
            title = _('Backup Failed')
            severity = 'danger'
            reason_text = sanitize_error_message(history.error_message or '')
            if 'encryption' in reason_text.lower():
                intro = _('Backup encryption failed.')
            else:
                intro = _('Backup failed.')

        values = [
            (_('Plan'), plan.name),
            (_('Database'), history.database_name or plan.database_name),
            (_('Backup'), history.file_name or _('Not created')),
            (_('Status'), dict(history._fields['status'].selection).get(status, status)),
            (_('Destinations'), dest_text.replace(' | ', '\n') if dest_text else ''),
            (_('Duration'), _('%s seconds') % int(history.duration_seconds or 0)),
            (_('Size'), format_bytes(history.file_size)),
        ]
        if history.backup_datetime:
            values.insert(3, (_('Backup datetime'), fields.Datetime.to_string(history.backup_datetime)))
        if history.encrypted:
            values.append((_('Encryption'), _('AES-256')))
        if reason:
            values.append((_('Reason'), reason))
        if html:
            return title, self._html_sections([(_('Summary'), intro)] + values), severity
        return title, self._text_sections([(_('Summary'), intro)] + values), severity

    def _cleanup_content(self, plan, logs, html=True):
        deleted = sum(logs.mapped('files_deleted'))
        failed_logs = logs.filtered(lambda log: log.status == 'failed')
        partial_logs = logs.filtered(lambda log: log.status == 'partial')
        bytes_deleted = sum(logs.mapped('bytes_deleted'))
        failed_count = len(failed_logs) + len(partial_logs)
        errors = [
            sanitize_error_message(message)
            for message in logs.mapped('error_message')
            if message
        ]
        if failed_logs and not deleted:
            title = _('Backup Cleanup Failed')
            intro = _('Backup cleanup failed.')
            severity = 'danger'
        elif failed_logs or partial_logs:
            title = _('Backup Cleanup Partially Completed')
            intro = _('Backup cleanup partially completed.')
            severity = 'warning'
        else:
            title = _('Backup Cleanup Completed')
            intro = _('Backup cleanup completed.')
            severity = 'success'
        values = [
            (_('Plan'), plan.name),
            (_('Deleted'), _('%s files') % deleted),
            (_('Freed'), format_bytes(bytes_deleted)),
        ]
        if failed_count:
            values.append((_('Failed'), failed_count))
        if errors:
            values.append((_('Reason'), errors[0]))
        if html:
            return title, self._html_sections([(_('Summary'), intro)] + values), severity
        return title, self._text_sections([(_('Summary'), intro)] + values), severity

    def _send_inbox(self, plan, subject, body, model=False, res_id=False):
        partners = plan._get_notification_partners()
        if not partners:
            return self.env['mail.message']
        try:
            return self.env['mail.thread'].sudo().message_notify(
                subject=subject,
                body=body,
                partner_ids=partners.ids,
                model=model,
                res_id=res_id,
                author_id=self.env.user.partner_id.id,
            )
        except Exception:
            _logger.exception(
                'Unable to send backup notification for plan %s (%s).',
                plan.name,
                plan.id,
            )
            return self.env['mail.message']

    def _client_notification(self, title, message, severity, sticky=False, action_record=False):
        params = {
            'title': title,
            'message': message,
            'type': severity,
            'sticky': sticky,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }

    def _backup_notification_key(self, history):
        if history.scheduled_occurrence:
            return 'backup:%s' % history.scheduled_occurrence
        return 'backup:history:%s' % history.id

    def _cleanup_notification_key(self, plan, logs, trigger):
        stamp = logs[:1].cleanup_datetime or fields.Datetime.now()
        return 'cleanup:%s:%s:%s' % (
            plan.id,
            trigger,
            fields.Datetime.to_string(stamp),
        )

    def _backup_already_notified(self, notification_key, history):
        if history.notification_sent:
            return True
        return bool(self.env['cb.backup.history'].sudo().search_count([
            ('id', '!=', history.id),
            ('notification_key', '=', notification_key),
            ('notification_sent', '=', True),
        ]))

    def _cleanup_already_notified(self, notification_key):
        return bool(self.env['cb.backup.cleanup.log'].sudo().search_count([
            ('notification_key', '=', notification_key),
            ('notification_sent', '=', True),
        ]))

    def _cleanup_outcome(self, logs):
        if logs.filtered(lambda log: log.status == 'failed') and not sum(logs.mapped('files_deleted')):
            return 'failed'
        if logs.filtered(lambda log: log.status in ('failed', 'partial')):
            return 'partial'
        return 'success'

    def _html_sections(self, sections):
        chunks = []
        for label, value in sections:
            if value in (None, False, ''):
                continue
            chunks.append(Markup('<p><strong>%s</strong><br/>%s</p>') % (
                str(label),
                Markup('<br/>').join(
                    Markup(html_escape(part)) for part in str(value).split('\n')
                ),
            ))
        return Markup('').join(chunks)

    def _text_sections(self, sections):
        lines = []
        for label, value in sections:
            if value in (None, False, ''):
                continue
            lines.append('%s:\n%s' % (label, value))
        return '\n\n'.join(lines)
