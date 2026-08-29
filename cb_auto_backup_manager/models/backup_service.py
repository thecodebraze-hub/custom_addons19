# -*- coding: utf-8 -*-
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import odoo
import odoo.release
import odoo.service.db as db_service
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config
from odoo.tools.misc import exec_pg_environ, find_pg_tool

from odoo.addons.cb_auto_backup_manager.models.backup_encryption import (
    encrypt_backup_file,
    restrict_file_permissions,
    unlink_quietly,
    validate_encrypted_container,
)
from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    FILESTORE_DIRNAME,
    MANIFEST_FILENAME,
    BackupError,
    build_backup_manifest,
    compute_sha256,
    create_backup_zip,
    format_destination_results,
    generate_backup_filename,
    sanitize_error_message,
    validate_database_name,
    verify_backup_zip,
    write_manifest_file,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)

_logger = logging.getLogger(__name__)

LOCK_NAMESPACE = 845920
PG_DUMP_TIMEOUT_SECONDS = 6 * 60 * 60


class CbBackupService(models.AbstractModel):
    _name = 'cb.backup.service'
    _description = 'Backup Service'

    @api.model
    def list_available_databases(self):
        """Return PostgreSQL databases visible to the Odoo process."""
        databases = []
        try:
            databases = list(db_service.list_dbs(force=True) or [])
        except Exception:
            _logger.warning(
                'Unable to list PostgreSQL databases from Odoo configuration. '
                'Falling back to the current database only.',
                exc_info=True,
            )
        if self.env.cr.dbname and self.env.cr.dbname not in databases:
            databases.append(self.env.cr.dbname)
        return sorted(set(databases))

    @api.model
    def database_exists(self, database_name):
        db_name = validate_database_name(database_name)
        if db_name in self.list_available_databases():
            return True
        try:
            self.env.cr.execute(
                """
                SELECT 1
                  FROM pg_database
                 WHERE datname = %s
                   AND datallowconn
                   AND NOT datistemplate
                """,
                (db_name,),
            )
            return bool(self.env.cr.fetchone())
        except Exception:
            _logger.exception('Unable to verify database existence for %s.', db_name)
            return False

    @api.model
    def validate_database_selection(self, database_name):
        db_name = validate_database_name(database_name)
        if not self.database_exists(db_name):
            raise BackupError(
                'Database "%s" does not exist or is not accessible on this Odoo server.'
                % db_name
            )
        return db_name

    @api.model
    def get_filestore_path(self, database_name):
        db_name = self.validate_database_selection(database_name)
        return Path(config.filestore(db_name))

    @api.model
    def require_filestore_path(self, database_name):
        """Return the validated filestore directory for the selected database."""
        db_name = self.validate_database_selection(database_name)
        filestore_path = self.get_filestore_path(db_name).resolve()

        # Never accept another database's filestore directory.
        if filestore_path.name != db_name or filestore_path.parent.name != 'filestore':
            raise BackupError(
                'Resolved filestore path does not belong to database "%s".' % db_name
            )
        if not filestore_path.is_dir():
            raise BackupError(
                'Filestore for database "%s" could not be found at: %s'
                % (db_name, filestore_path)
            )
        return filestore_path

    @api.model
    def execute_plan_backup(self, plan, trigger='manual', schedule=None):
        plan.ensure_one()
        plan._check_backup_execute_access()

        if trigger == 'scheduled' and (not plan.active or plan.state != 'active'):
            _logger.info(
                'Skipping backup for plan %s (%s): plan is not active (state=%s, active=%s).',
                plan.name,
                plan.id,
                plan.state,
                plan.active,
            )
            return False

        lock_key = LOCK_NAMESPACE * 1000000 + plan.id
        self.env.cr.execute('SELECT pg_try_advisory_lock(%s)', (lock_key,))
        if not self.env.cr.fetchone()[0]:
            _logger.info(
                'Skipping backup for plan %s (%s): advisory lock already held.',
                plan.name,
                plan.id,
            )
            return False

        history = False
        try:
            if plan._has_running_backup():
                _logger.info(
                    'Skipping backup for plan %s (%s): another backup is running.',
                    plan.name,
                    plan.id,
                )
                return False

            occurrence_key = False
            if trigger == 'scheduled' and schedule:
                now_local = plan._get_local_now()
                occurrence_key = schedule.get_occurrence_key(now_local)
                if schedule._already_ran_this_slot(now_local) or schedule._occurrence_already_processed(now_local):
                    _logger.info(
                        'Skipping backup for plan %s (%s): occurrence %s already processed.',
                        plan.name,
                        plan.id,
                        occurrence_key,
                    )
                    return False

            history = plan._create_running_history(
                trigger=trigger,
                schedule=schedule,
                scheduled_occurrence=occurrence_key,
            )
            if occurrence_key:
                history.notification_key = 'backup:%s' % occurrence_key
            plan._validate_for_backup()
            result = self._run_backup_pipeline(plan)
            plan._finalize_backup_history(history, result)
            stored = history.status in ('success', 'partial')
            plan._update_backup_datetimes(stored, schedule=schedule)
            if stored:
                try:
                    logs = self.env['cb.backup.cleanup.service'].cleanup_plan(
                        plan,
                        trigger='after_backup',
                    )
                    if logs:
                        self.env['cb.backup.notification.service'].notify_cleanup(
                            plan, logs, trigger='after_backup',
                        )
                except Exception as cleanup_exc:
                    _logger.exception(
                        'Retention cleanup failed after backup for plan %s (%s).',
                        plan.name,
                        plan.id,
                    )
                    self.env['cb.backup.notification.service'].notify_cleanup_error(
                        plan, str(cleanup_exc), trigger='after_backup',
                    )
            self.env['cb.backup.notification.service'].notify_backup(plan, history, trigger)
            if trigger == 'manual':
                return plan._build_manual_backup_notification(history)
            return stored
        except BackupError as exc:
            message = sanitize_error_message(str(exc))
            _logger.warning('Backup failed for plan %s (%s): %s', plan.name, plan.id, message)
            if history:
                plan._finalize_backup_history(history, {
                    'success': False,
                    'error_message': message,
                    'destination_results': [],
                    'start_datetime': history.start_datetime,
                    'end_datetime': fields.Datetime.now(),
                })
                self.env['cb.backup.notification.service'].notify_backup(plan, history, trigger)
            if trigger == 'manual':
                if history:
                    return plan._build_manual_backup_notification(history)
                raise UserError(message) from exc
            return False
        except Exception as exc:
            message = sanitize_error_message(str(exc))
            _logger.exception('Unexpected backup failure for plan %s (%s)', plan.name, plan.id)
            if history:
                plan._finalize_backup_history(history, {
                    'success': False,
                    'error_message': message,
                    'destination_results': [],
                    'start_datetime': history.start_datetime,
                    'end_datetime': fields.Datetime.now(),
                })
                self.env['cb.backup.notification.service'].notify_backup(plan, history, trigger)
            if trigger == 'manual':
                if history:
                    return plan._build_manual_backup_notification(history)
                raise UserError(message) from exc
            return False
        finally:
            self.env.cr.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))

    @api.model
    def _run_backup_pipeline(self, plan):
        db_name = self.validate_database_selection(plan.database_name)
        destinations = plan.storage_destination_ids.filtered('active')
        if not destinations:
            raise BackupError('At least one active storage destination is required.')

        start_dt = fields.Datetime.now()
        backup_dt = datetime.utcnow()
        encrypt = bool(plan.encryption_enabled)
        zip_filename = generate_backup_filename(db_name, backup_dt, encrypted=False)
        temp_dir = Path(tempfile.mkdtemp(prefix='cb_backup_'))
        verified_zip = temp_dir / zip_filename

        try:
            workspace = temp_dir / 'workspace'
            workspace.mkdir()
            dump_path = workspace / DATABASE_DUMP_FILENAME
            self._run_pg_dump(db_name, dump_path)

            filestore_path = self.require_filestore_path(db_name)
            shutil.copytree(
                filestore_path,
                workspace / FILESTORE_DIRNAME,
                dirs_exist_ok=True,
            )

            manifest = build_backup_manifest(
                database_name=db_name,
                backup_datetime=backup_dt,
                odoo_version=odoo.release.version,
                module_version=plan._get_module_version(),
                filestore_included=True,
                filestore_missing=False,
                plan_id=plan.id,
                plan_identifier=plan.get_storage_relative_dir().rsplit('/', 1)[-1],
                encryption_method='aes256' if encrypt else 'none',
            )
            write_manifest_file(workspace / MANIFEST_FILENAME, manifest)

            create_backup_zip(workspace, verified_zip)
            restrict_file_permissions(verified_zip)
            verify_backup_zip(verified_zip)

            artifact = verified_zip
            filename = zip_filename
            if encrypt:
                secret = plan.encryption_profile_id.sudo()._get_plaintext_secret()
                if not secret:
                    raise BackupError('The encryption profile does not have a password configured.')
                enc_filename = generate_backup_filename(db_name, backup_dt, encrypted=True)
                enc_path = temp_dir / enc_filename
                try:
                    encrypt_backup_file(
                        verified_zip,
                        enc_path,
                        secret,
                        database_name=db_name,
                        plan_id=plan.id,
                        backup_datetime=backup_dt.isoformat(),
                    )
                    validate_encrypted_container(enc_path)
                except BackupError:
                    unlink_quietly(enc_path)
                    raise
                except Exception as exc:
                    unlink_quietly(enc_path)
                    raise BackupError('Backup encryption failed.') from exc
                unlink_quietly(verified_zip)
                if verified_zip.exists():
                    raise BackupError('Unencrypted backup ZIP could not be removed after encryption.')
                artifact = enc_path
                filename = enc_filename

            checksum = compute_sha256(artifact)
            file_size = artifact.stat().st_size

            destination_results = self._deliver_to_destinations(
                destinations,
                artifact,
                filename,
                plan=plan,
            )
            overall_success = all(result.success for result in destination_results)
            primary_path = next(
                (result.final_path for result in destination_results if result.success and result.final_path),
                '',
            )

            return {
                'success': overall_success,
                'database_name': db_name,
                'filename': filename,
                'file_path': primary_path,
                'file_size': file_size,
                'checksum': checksum,
                'encrypted': encrypt,
                'encryption_method': 'aes256' if encrypt else 'none',
                'start_datetime': start_dt,
                'end_datetime': fields.Datetime.now(),
                'destination_results': destination_results,
                'error_message': '' if overall_success else format_destination_results(destination_results),
                'filestore_missing': False,
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @api.model
    def _run_pg_dump(self, database_name, dump_path):
        try:
            pg_dump = find_pg_tool('pg_dump')
        except Exception as exc:
            raise BackupError('pg_dump was not found on the server.') from exc

        cmd = [
            pg_dump,
            '--no-owner',
            '--file',
            str(dump_path),
            database_name,
        ]
        try:
            completed = subprocess.run(
                cmd,
                env=exec_pg_environ(),
                capture_output=True,
                text=True,
                check=False,
                timeout=PG_DUMP_TIMEOUT_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackupError(
                'Database backup failed because PostgreSQL dump timed out. '
                'Try again during a quieter window.'
            ) from exc

        if completed.returncode != 0:
            stderr = sanitize_error_message(completed.stderr or completed.stdout or '')
            raise BackupError(
                'Database backup failed. Check PostgreSQL availability and permissions. '
                'See Backup History for details: %s' % stderr
            )

        if not dump_path.is_file() or dump_path.stat().st_size == 0:
            raise BackupError('pg_dump did not produce a valid database dump file.')

    @api.model
    def _deliver_to_destinations(self, destinations, zip_path, filename, plan=None):
        results = []
        relative_dir = plan.get_storage_relative_dir() if plan else ''
        artifact_name = Path(filename).name
        if artifact_name != filename or not (
            artifact_name.endswith('.zip') or artifact_name.endswith('.enc')
        ):
            raise BackupError('Backup filename is invalid.')
        for destination in destinations.sorted(key=lambda dest: dest.id):
            started = fields.Datetime.now()
            provider = get_storage_provider(destination)
            result = provider.store(str(zip_path), filename, relative_dir=relative_dir)
            result.started = started
            result.completed = fields.Datetime.now()
            results.append(result)
            _logger.info(
                'Backup delivery to %s (%s): %s',
                destination.name,
                destination.type,
                result.status,
            )
        return results

    @api.model
    def run_due_scheduled_backups(self):
        """Execute backups for all due schedule lines."""
        plans = self.env['cb.backup.plan'].search([
            ('active', '=', True),
            ('state', '=', 'active'),
        ])
        executed = 0
        for plan in plans:
            try:
                due_schedules = plan._get_due_schedules()
                for schedule in due_schedules:
                    if self.execute_plan_backup(plan, trigger='scheduled', schedule=schedule):
                        executed += 1
            except Exception:
                _logger.exception(
                    'Scheduled backup failed for plan %s (%s). Continuing with remaining plans.',
                    plan.name,
                    plan.id,
                )
        _logger.info('CB Auto Backup Manager scheduler finished. Executed backups: %s', executed)
        return executed
