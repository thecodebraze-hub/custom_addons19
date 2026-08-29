# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

from pathlib import Path

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    BackupError,
    calculate_retention_cutoff,
    identify_managed_backup,
    is_older_than_cutoff,
    is_path_inside,
    plan_relative_storage_dir,
    sanitize_error_message,
)
from odoo.addons.cb_auto_backup_manager.models.backup_service import LOCK_NAMESPACE
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)

_logger = logging.getLogger(__name__)

CLEANUP_MIN_INTERVAL_MINUTES = 60


class CbBackupCleanupService(models.AbstractModel):
    _name = 'cb.backup.cleanup.service'
    _description = 'Backup Cleanup Service'

    @api.model
    def cleanup_plan(self, plan, trigger='scheduled'):
        """Run retention cleanup for one plan across its active destinations."""
        plan.ensure_one()
        if trigger != 'manual' and (not plan.active or plan.state != 'active'):
            _logger.info(
                'Skipping cleanup for plan %s (%s): plan is not active.',
                plan.name,
                plan.id,
            )
            return False

        if not plan.retention_days or plan.retention_days <= 0:
            raise BackupError('Retention days must be greater than zero.')

        now = fields.Datetime.now()
        cutoff = calculate_retention_cutoff(now, plan.retention_days)
        destinations = plan.storage_destination_ids.filtered('active')
        if not destinations:
            raise BackupError('At least one active storage destination is required.')

        logs = self.env['cb.backup.cleanup.log']
        for storage in destinations:
            try:
                log = self._cleanup_destination(plan, storage, cutoff, trigger)
                logs |= log
            except Exception as exc:
                _logger.exception(
                    'Retention cleanup failed for plan %s destination %s.',
                    plan.name,
                    storage.name,
                )
                logs |= self._create_log(
                    plan,
                    storage,
                    cutoff,
                    trigger,
                    status='failed',
                    error_message=sanitize_error_message(str(exc)),
                )

        plan.write({'last_cleanup_datetime': now})
        return logs

    @api.model
    def run_due_retention_cleanup(self):
        """Independent scheduled cleanup for active plans that are due."""
        plans = self.env['cb.backup.plan'].search([
            ('active', '=', True),
            ('state', '=', 'active'),
        ])
        cleaned = 0
        now = fields.Datetime.now()
        min_delta = timedelta(minutes=CLEANUP_MIN_INTERVAL_MINUTES)
        for plan in plans:
            if plan.last_cleanup_datetime and (now - plan.last_cleanup_datetime) < min_delta:
                continue
            lock_key = LOCK_NAMESPACE * 1000000 + plan.id
            self.env.cr.execute('SELECT pg_try_advisory_lock(%s)', (lock_key,))
            if not self.env.cr.fetchone()[0]:
                _logger.info(
                    'Skipping cleanup for plan %s (%s): backup or cleanup already running.',
                    plan.name,
                    plan.id,
                )
                continue
            try:
                if plan._has_running_backup():
                    _logger.info(
                        'Skipping cleanup for plan %s (%s): a backup is currently running.',
                        plan.name,
                        plan.id,
                    )
                    continue
                logs = self.cleanup_plan(plan, trigger='scheduled')
                if logs:
                    self.env['cb.backup.notification.service'].notify_cleanup(
                        plan, logs, trigger='scheduled',
                    )
                cleaned += 1
            except Exception as exc:
                _logger.exception(
                    'Scheduled retention cleanup failed for plan %s (%s).',
                    plan.name,
                    plan.id,
                )
                self.env['cb.backup.notification.service'].notify_cleanup_error(
                    plan, str(exc), trigger='scheduled',
                )
            finally:
                self.env.cr.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))
        _logger.info('CB Auto Backup Manager cleanup finished. Plans processed: %s', cleaned)
        return cleaned

    @api.model
    def _cleanup_destination(self, plan, storage, cutoff, trigger):
        provider = get_storage_provider(storage)
        relative_dir = plan_relative_storage_dir(plan.database_name, plan.id)
        details = []
        scanned = 0
        deleted = 0
        skipped = 0
        bytes_deleted = 0.0
        status = 'success'
        error_message = ''

        listed = provider.list_backups(
            relative_dir=relative_dir,
            database_name=plan.database_name,
            plan_id=plan.id,
        )
        if listed.is_not_implemented:
            return self._create_log(
                plan, storage, cutoff, trigger,
                status='failed',
                error_message=listed.error_message,
                details=listed.error_message,
            )
        if not listed.success:
            return self._create_log(
                plan, storage, cutoff, trigger,
                status='failed',
                error_message=listed.error_message or 'Unable to list backups.',
            )

        candidates = list(listed.files)
        candidates.extend(self._legacy_history_candidates(plan, storage, provider, listed.files))
        protected_names = set(plan.history_ids.filtered(
            lambda h: h.status == 'running'
        ).mapped('file_name'))

        seen_paths = set()
        for item in candidates:
            path = item.path
            if path in seen_paths:
                continue
            seen_paths.add(path)
            scanned += 1

            if item.filename in protected_names:
                skipped += 1
                details.append('SKIP %s: backup currently running.' % item.filename)
                continue
            if not item.identified:
                skipped += 1
                details.append('SKIP %s: %s' % (item.filename, item.skip_reason or 'not identified'))
                continue
            if item.plan_id and item.plan_id != plan.id:
                skipped += 1
                details.append('SKIP %s: belongs to another plan.' % item.filename)
                continue
            if not is_older_than_cutoff(item.backup_datetime, cutoff):
                skipped += 1
                details.append('KEEP %s: within retention period.' % item.filename)
                continue

            delete_result = provider.delete_backup(item.path)
            if delete_result.success:
                deleted += 1
                bytes_deleted += delete_result.file_size or item.size or 0
                details.append('DELETE %s' % item.filename)
                self._mark_history_deleted(plan, storage, item)
            else:
                skipped += 1
                status = 'partial'
                reason = delete_result.error_message or delete_result.status
                details.append('SKIP %s: %s' % (item.filename, reason))

        if status == 'partial' and deleted == 0 and scanned:
            error_message = 'No eligible files could be deleted.'
        return self._create_log(
            plan, storage, cutoff, trigger,
            files_scanned=scanned,
            files_deleted=deleted,
            files_skipped=skipped,
            bytes_deleted=bytes_deleted,
            status=status,
            error_message=error_message,
            details='\n'.join(details),
        )

    @api.model
    def _legacy_history_candidates(self, plan, storage, provider, already_listed):
        """Include Step 2 files stored in the destination root and still linked to this plan."""
        from odoo.addons.cb_auto_backup_manager.services.storage_providers.base import ListedBackup

        listed_paths = {item.path for item in already_listed}
        histories = plan.history_ids.filtered(
            lambda h: h.status == 'success' and not h.file_deleted and h.file_path
        )
        extra = []
        for history in histories:
            dest_lines = history.destination_result_ids.filtered(
                lambda line: line.storage_id.id == storage.id and line.file_path
            )
            paths = dest_lines.mapped('file_path') or ([history.file_path] if history.file_path else [])
            for path in paths:
                if path in listed_paths:
                    continue
                if storage.type == 'local' and storage.local_path and not is_path_inside(storage.local_path, path):
                    continue
                if storage.type == 'sftp':
                    from odoo.addons.cb_auto_backup_manager.models.backup_utils import is_sftp_path_inside
                    if storage.sftp_remote_path and not is_sftp_path_inside(storage.sftp_remote_path, path):
                        continue
                    extra.append(ListedBackup(
                        path=path,
                        filename=history.file_name or path.rsplit('/', 1)[-1],
                        size=history.file_size or 0,
                        backup_datetime=history.backup_datetime,
                        database_name=plan.database_name,
                        plan_id=plan.id,
                        identified=True,
                        skip_reason='',
                    ))
                    continue
                if not Path(path).is_file():
                    continue
                identified, manifest, skip_reason = identify_managed_backup(
                    path,
                    plan.database_name,
                    plan_id=plan.id,
                    require_plan_id=False,
                )
                extra.append(ListedBackup(
                    path=path,
                    filename=history.file_name or path.rsplit('\\', 1)[-1].rsplit('/', 1)[-1],
                    size=history.file_size or 0,
                    backup_datetime=history.backup_datetime,
                    database_name=plan.database_name,
                    plan_id=plan.id,
                    identified=identified,
                    skip_reason='' if identified else (skip_reason or 'Not a managed backup file.'),
                ))
        return extra

    @api.model
    def _mark_history_deleted(self, plan, storage, item):
        now = fields.Datetime.now()
        lines = self.env['cb.backup.history.destination'].search([
            ('history_id.plan_id', '=', plan.id),
            ('storage_id', '=', storage.id),
            ('file_path', '=', item.path),
        ])
        if lines:
            lines.write({
                'file_deleted': True,
                'file_deleted_datetime': now,
            })
        histories = plan.history_ids.filtered(
            lambda h: not h.file_deleted and h.file_path == item.path
        ) | lines.mapped('history_id').filtered(lambda h: not h.file_deleted)
        for history in histories:
            remaining = history.destination_result_ids.filtered(
                lambda line: line.status == 'success' and not line.file_deleted and line.file_path
            )
            if history.file_path == item.path or not remaining:
                history.write({
                    'file_deleted': True,
                    'file_deleted_datetime': now,
                })

    @api.model
    def _create_log(self, plan, storage, cutoff, trigger, **values):
        vals = {
            'plan_id': plan.id,
            'storage_id': storage.id,
            'cleanup_datetime': fields.Datetime.now(),
            'cutoff_datetime': cutoff,
            'trigger_type': trigger,
            'files_scanned': values.get('files_scanned', 0),
            'files_deleted': values.get('files_deleted', 0),
            'files_skipped': values.get('files_skipped', 0),
            'bytes_deleted': values.get('bytes_deleted', 0.0),
            'status': values.get('status', 'success'),
            'error_message': sanitize_error_message(values.get('error_message') or '') if values.get('error_message') else False,
            'details': values.get('details') or False,
        }
        return self.env['cb.backup.cleanup.log'].create(vals)
