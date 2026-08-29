# -*- coding: utf-8 -*-
import logging
import shutil
import subprocess
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

import odoo
import odoo.release
import odoo.sql_db
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.sql_db import db_connect
from odoo.tools import SQL
from odoo.tools.misc import exec_pg_environ, find_pg_tool

from odoo.addons.cb_auto_backup_manager.models.backup_encryption import (
    DECRYPT_FAILED_MESSAGE,
    decrypt_backup_file,
    is_encrypted_backup_file,
    unlink_quietly,
    validate_encrypted_container,
)
from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    FILESTORE_DIRNAME,
    PROTECTED_DATABASE_NAMES,
    BackupError,
    compare_odoo_versions,
    compute_sha256,
    detect_dump_format,
    extract_zip_safely,
    generate_temp_restore_database_name,
    is_temp_restore_database_name,
    resolve_dump_path,
    sanitize_error_message,
    validate_database_name,
    validate_restore_archive,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)
from odoo.service.db import database_identifier

_logger = logging.getLogger(__name__)

PG_RESTORE_TIMEOUT_SECONDS = 6 * 60 * 60
EXPECTED_ODOO_TABLES = (
    'ir_module_module',
    'ir_model',
    'ir_config_parameter',
    'res_users',
    'res_partner',
)


class CbBackupRestoreService(models.AbstractModel):
    _name = 'cb.backup.restore.service'
    _description = 'Backup Restore Service'

    @api.model
    def verify_backup(self, history, storage=None, encryption_secret=None):
        """Verify a backup archive without creating a database."""
        self._check_verify_access()
        return self._run_restore(
            history,
            restore_mode='verify_only',
            storage=storage,
            verify_database=False,
            verify_filestore=True,
            cleanup_after_test=True,
            acknowledge_version_warning=True,
            encryption_secret=encryption_secret,
        )

    @api.model
    def test_restore(self, history, storage=None, verify_database=True,
                     verify_filestore=True, cleanup_after_test=True,
                     acknowledge_version_warning=False, target_database_name=None,
                     encryption_secret=None):
        """Restore into a temporary database created by this module."""
        self._check_restore_access()
        return self._run_restore(
            history,
            restore_mode='temporary_restore',
            storage=storage,
            verify_database=verify_database,
            verify_filestore=verify_filestore,
            cleanup_after_test=cleanup_after_test,
            acknowledge_version_warning=acknowledge_version_warning,
            target_database_name=target_database_name,
            encryption_secret=encryption_secret,
        )

    def _run_restore(self, history, restore_mode, storage=None, verify_database=True,
                     verify_filestore=True, cleanup_after_test=True,
                     acknowledge_version_warning=False, target_database_name=None,
                     encryption_secret=None):
        history.ensure_one()
        start = fields.Datetime.now()
        log = self.env['cb.backup.restore.log'].create({
            'history_id': history.id,
            'restore_datetime': start,
            'restore_mode': restore_mode,
            'status': 'running',
            'storage_id': storage.id if storage else False,
        })
        workspace = None
        created_database = ''
        result = {
            'success': False,
            'status': 'failed',
            'message': _('Backup restore test failed.'),
            'log': log,
            'checksum_verified': False,
            'database_verified': False,
            'filestore_verified': False,
            'odoo_version_compatible': False,
            'target_database': False,
            'cleanup_status': 'skipped',
            'error_message': '',
            'backup_odoo_version': '',
            'current_odoo_version': odoo.release.version,
        }
        try:
            if history.file_deleted or history.file_storage_status in ('deleted', 'none'):
                raise BackupError('Backup file is no longer available.')

            workspace = Path(tempfile.mkdtemp(prefix='cb_restore_'))
            artifact_path = self._retrieve_backup(history, workspace, storage=storage)
            zip_path = self._prepare_restore_zip(
                history,
                artifact_path,
                workspace,
                encryption_secret=encryption_secret,
            )
            result['checksum_verified'] = True
            manifest = validate_restore_archive(zip_path)
            result['backup_odoo_version'] = manifest.get('odoo_version') or ''
            compatible, major_mismatch, version_warning = compare_odoo_versions(
                result['backup_odoo_version'],
                result['current_odoo_version'],
            )
            result['odoo_version_compatible'] = compatible and not major_mismatch

            if restore_mode == 'temporary_restore' and major_mismatch and not acknowledge_version_warning:
                raise BackupError(version_warning)

            if restore_mode == 'verify_only':
                if verify_filestore:
                    extract_dir = workspace / 'extracted'
                    extract_zip_safely(zip_path, extract_dir)
                    self._validate_extracted_filestore(extract_dir / FILESTORE_DIRNAME)
                    result['filestore_verified'] = True
                result['success'] = True
                if version_warning and not major_mismatch:
                    result['status'] = 'warning'
                    result['message'] = _(
                        'Backup is valid, but Odoo version compatibility requires review.'
                    )
                    result['error_message'] = version_warning
                elif major_mismatch:
                    result['status'] = 'warning'
                    result['message'] = _(
                        'Backup is valid, but Odoo version compatibility requires review.'
                    )
                    result['error_message'] = version_warning
                else:
                    result['status'] = 'success'
                    result['message'] = _('Backup verification successful.')
            else:
                extract_dir = workspace / 'extracted'
                extract_zip_safely(zip_path, extract_dir)
                dump_path = resolve_dump_path(extract_dir)
                if verify_filestore:
                    self._validate_extracted_filestore(extract_dir / FILESTORE_DIRNAME)
                    result['filestore_verified'] = True

                created_database = self._create_temp_database(
                    history.database_name or manifest.get('database_name'),
                    history.backup_datetime,
                    requested_name=target_database_name,
                )
                result['target_database'] = created_database
                log.write({
                    'target_database': created_database,
                    'created_database': True,
                })
                self._restore_dump(dump_path, created_database)
                if verify_database:
                    self._validate_temp_database(created_database)
                    result['database_verified'] = True
                result['success'] = True
                if version_warning:
                    result['status'] = 'warning'
                    result['message'] = _(
                        'Backup restored and verified successfully in temporary database.'
                    )
                    result['error_message'] = version_warning
                else:
                    result['status'] = 'success'
                    result['message'] = _(
                        'Backup restored and verified successfully in temporary database.'
                    )
        except BackupError as exc:
            result['error_message'] = sanitize_error_message(str(exc))
            result['status'] = 'failed'
            result['success'] = False
            if result['error_message'] == DECRYPT_FAILED_MESSAGE:
                result['message'] = _('Backup could not be decrypted.')
            elif restore_mode == 'verify_only':
                result['message'] = _('Backup verification failed.')
            else:
                result['message'] = _('Backup restore test failed.')
            _logger.warning(
                'Backup restore %s failed for history %s: %s',
                restore_mode,
                history.id,
                result['error_message'],
            )
        except Exception as exc:
            result['error_message'] = sanitize_error_message(str(exc))
            result['status'] = 'failed'
            result['success'] = False
            result['message'] = (
                _('Backup verification failed.')
                if restore_mode == 'verify_only'
                else _('Backup restore test failed.')
            )
            _logger.exception(
                'Unexpected restore failure for history %s.',
                history.id,
            )
        finally:
            cleanup_status = 'skipped'
            if created_database and cleanup_after_test:
                try:
                    self._drop_temp_database(created_database, log)
                    cleanup_status = 'cleaned'
                except Exception as exc:
                    cleanup_status = 'failed'
                    extra = sanitize_error_message(str(exc))
                    result['error_message'] = (
                        '%s\n%s' % (result['error_message'], extra)
                        if result['error_message'] else extra
                    )
                    _logger.warning(
                        'Temporary restore cleanup failed for %s: %s',
                        created_database,
                        extra,
                    )
            elif created_database:
                cleanup_status = 'pending'
            if workspace:
                try:
                    shutil.rmtree(workspace, ignore_errors=False)
                except OSError as exc:
                    cleanup_status = 'failed'
                    extra = sanitize_error_message('Unable to delete temporary workspace: %s' % exc)
                    result['error_message'] = (
                        '%s\n%s' % (result['error_message'], extra)
                        if result['error_message'] else extra
                    )
            result['cleanup_status'] = cleanup_status
            duration = (fields.Datetime.now() - start).total_seconds()
            log.write({
                'status': result['status'],
                'duration_seconds': duration,
                'database_verified': result['database_verified'],
                'filestore_verified': result['filestore_verified'],
                'checksum_verified': result['checksum_verified'],
                'odoo_version_compatible': result['odoo_version_compatible'],
                'cleanup_status': cleanup_status,
                'error_message': result['error_message'] or False,
                'result_message': result['message'],
                'backup_odoo_version': result['backup_odoo_version'] or False,
                'current_odoo_version': result['current_odoo_version'] or False,
                'target_database': result['target_database'] or log.target_database,
            })
            self._update_history_restore_fields(history, log)
            result['log'] = log
        return result

    def _retrieve_backup(self, history, workspace, storage=None):
        filename = history.file_name or 'backup.zip'
        suffix = Path(filename).suffix if Path(filename).suffix in ('.zip', '.enc') else '.bin'
        local_path = Path(workspace) / ('backup%s' % suffix)
        source = self._select_backup_source(history, storage=storage)
        if not source:
            raise BackupError('No available backup file was found for this history record.')
        storage_record, remote_path = source
        if storage_record:
            provider = get_storage_provider(storage_record)
            download = provider.download_backup(remote_path, local_path)
            if download.is_not_implemented:
                raise BackupError(download.error_message or 'Download is not implemented for this destination.')
            if not download.success:
                raise BackupError(download.error_message or 'Unable to retrieve the backup file.')
            return local_path
        source_path = Path(remote_path)
        if not source_path.is_file():
            raise BackupError('Backup file does not exist.')
        shutil.copy2(source_path, local_path)
        return local_path

    def _prepare_restore_zip(self, history, artifact_path, workspace, encryption_secret=None):
        artifact = Path(artifact_path)
        encrypted = bool(history.encrypted) or is_encrypted_backup_file(artifact)
        if history.checksum:
            actual = compute_sha256(artifact)
            if actual.lower() != (history.checksum or '').lower():
                raise BackupError(
                    'Backup integrity verification failed. '
                    'The backup file may be corrupted or modified.'
                )
        if not encrypted:
            return artifact
        validate_encrypted_container(artifact)
        if not encryption_secret:
            raise BackupError('This backup is encrypted. Enter the encryption secret.')
        zip_path = Path(workspace) / 'backup.zip'
        try:
            decrypt_backup_file(artifact, zip_path, encryption_secret)
        except BackupError as exc:
            unlink_quietly(zip_path)
            message = str(exc)
            if message == DECRYPT_FAILED_MESSAGE:
                raise
            if 'corrupted' in message.lower() or 'modified' in message.lower():
                raise
            raise BackupError(DECRYPT_FAILED_MESSAGE) from exc
        return zip_path

    def _select_backup_source(self, history, storage=None):
        lines = history.destination_result_ids.filtered(
            lambda line: line.status == 'success' and not line.file_deleted and line.file_path
        )
        if storage:
            lines = lines.filtered(lambda line: line.storage_id == storage)
            if not lines:
                return False
            return lines[:1].storage_id, lines[:1].file_path
        preferred = lines.filtered(lambda line: line.storage_type == 'local') or lines
        if preferred:
            line = preferred[:1]
            return line.storage_id, line.file_path
        if history.file_path and Path(history.file_path).is_file():
            return False, history.file_path
        return False

    def _validate_extracted_filestore(self, filestore_dir):
        path = Path(filestore_dir)
        if not path.exists() or not path.is_dir():
            raise BackupError('Extracted filestore directory is missing.')
        readable = False
        for entry in path.rglob('*'):
            if entry.is_symlink():
                raise BackupError('Extracted filestore contains an unsafe symbolic link.')
            if entry.is_file():
                with entry.open('rb') as handle:
                    handle.read(1)
                readable = True
                break
        if not readable:
            try:
                next(path.iterdir())
                readable = True
            except StopIteration:
                readable = True
            except OSError as exc:
                raise BackupError('Extracted filestore is not readable.') from exc
        live_filestore = Path(odoo.tools.config.filestore(self.env.cr.dbname)).resolve()
        if path.resolve() == live_filestore:
            raise BackupError('Refusing to use the live Odoo filestore for a restore test.')
        return True

    def _create_temp_database(self, source_database, backup_dt, requested_name=None):
        if requested_name:
            name = validate_database_name(requested_name)
            if not is_temp_restore_database_name(name):
                raise BackupError('Invalid database name.')
        else:
            stamp = fields.Datetime.to_datetime(backup_dt) if backup_dt else datetime.utcnow()
            name = generate_temp_restore_database_name(source_database, stamp)

        for _attempt in range(8):
            self._assert_not_live_or_protected(name, destructive=True)
            if self._pg_database_exists(name):
                name = generate_temp_restore_database_name(source_database)
                continue
            self._create_empty_database(name)
            return name
        raise BackupError('Unable to allocate a unique temporary database name.')

    def _create_empty_database(self, name):
        self._assert_not_live_or_protected(name, destructive=True)
        if not is_temp_restore_database_name(name):
            raise BackupError('Invalid database name.')
        if self._pg_database_exists(name):
            raise BackupError('Temporary database name already exists.')
        db = db_connect('postgres')
        with closing(db.cursor()) as cr:
            cr.rollback()
            cr._cnx.autocommit = True
            cr.execute(SQL(
                "CREATE DATABASE %s ENCODING 'unicode' TEMPLATE %s",
                database_identifier(cr, name),
                database_identifier(cr, 'template0'),
            ))
        _logger.info('Created temporary restore database %s.', name)

    def _restore_dump(self, dump_path, database_name):
        self._assert_not_live_or_protected(database_name, destructive=True)
        dump_format = detect_dump_format(dump_path)
        env = exec_pg_environ()
        if dump_format == 'custom':
            try:
                tool = find_pg_tool('pg_restore')
            except Exception as exc:
                raise BackupError('pg_restore was not found on the server.') from exc
            cmd = [
                tool,
                '--no-owner',
                '--no-acl',
                '--dbname=%s' % database_name,
                str(dump_path),
            ]
        else:
            try:
                tool = find_pg_tool('psql')
            except Exception as exc:
                raise BackupError('psql was not found on the server.') from exc
            cmd = [
                tool,
                '-q',
                '-d',
                database_name,
                '-f',
                str(dump_path),
            ]
        try:
            completed = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=PG_RESTORE_TIMEOUT_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackupError(
                'Temporary database restore timed out. The live Odoo database was not changed.'
            ) from exc
        if completed.returncode != 0:
            stderr = sanitize_error_message(completed.stderr or completed.stdout or '')
            raise BackupError(
                'Temporary database restore failed. The live Odoo database was not changed. '
                'Details: %s' % stderr
            )

    def _validate_temp_database(self, database_name):
        self._assert_not_live_or_protected(database_name, destructive=False)
        if not self._pg_database_exists(database_name):
            raise BackupError('Temporary database does not exist after restore.')
        try:
            db = db_connect(database_name)
            with closing(db.cursor()) as cr:
                cr.execute('SELECT 1')
                if not cr.fetchone():
                    raise BackupError('Temporary database could not be queried.')
                cr.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
                tables = {row[0] for row in cr.fetchall()}
                if not tables:
                    raise BackupError('Temporary database is empty.')
                missing = [name for name in EXPECTED_ODOO_TABLES if name not in tables]
                if missing:
                    raise BackupError('Temporary database is missing expected Odoo tables.')
                if 'ir_module_module' in tables:
                    cr.execute('SELECT COUNT(*) FROM ir_module_module')
                    count = cr.fetchone()[0]
                    if not count:
                        raise BackupError('Temporary database Odoo metadata is empty.')
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError('Temporary database validation failed.') from exc

    def _drop_temp_database(self, database_name, restore_log):
        self._assert_safe_drop(database_name, restore_log)
        odoo.sql_db.close_db(database_name)
        db = db_connect('postgres')
        with closing(db.cursor()) as cr:
            cr.rollback()
            cr._cnx.autocommit = True
            self._terminate_backends(cr, database_name)
            cr.execute(SQL('DROP DATABASE %s', database_identifier(cr, database_name)))
        _logger.info('Dropped temporary restore database %s.', database_name)

    def _assert_safe_drop(self, database_name, restore_log):
        name = validate_database_name(database_name)
        self._assert_not_live_or_protected(name, destructive=True)
        if not is_temp_restore_database_name(name):
            raise BackupError('Refusing to drop a database that was not created by this restore test.')
        if not restore_log or restore_log.target_database != name or not restore_log.created_database:
            raise BackupError('Refusing to drop a database that is not referenced by this restore log.')

    def _assert_not_live_or_protected(self, database_name, destructive=True):
        name = validate_database_name(database_name)
        current = self.env.cr.dbname
        if name == current:
            raise BackupError('The current Odoo database is protected and cannot be modified.')
        if name in PROTECTED_DATABASE_NAMES:
            raise BackupError('Refusing to modify a PostgreSQL system database.')
        if destructive and self._is_configured_plan_database(name):
            raise BackupError('Refusing to modify a database configured on a backup plan.')

    def _is_configured_plan_database(self, database_name):
        return bool(self.env['cb.backup.plan'].sudo().search_count([
            ('database_name', '=', database_name),
        ]))

    def _pg_database_exists(self, database_name):
        name = validate_database_name(database_name)
        db = db_connect('postgres')
        with closing(db.cursor()) as cr:
            cr.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (name,),
            )
            return bool(cr.fetchone())

    def _terminate_backends(self, cr, database_name):
        try:
            cr.execute(
                """
                SELECT pg_terminate_backend(pid)
                  FROM pg_stat_activity
                 WHERE datname = %s
                   AND pid != pg_backend_pid()
                """,
                (database_name,),
            )
        except Exception:
            _logger.debug('Unable to terminate backends for %s.', database_name, exc_info=True)

    def _update_history_restore_fields(self, history, log):
        vals = {}
        if log.restore_mode == 'verify_only':
            vals['last_verified_datetime'] = log.restore_datetime
            vals['verification_status'] = (
                'verified' if log.status in ('success', 'warning') else 'failed'
            )
        else:
            vals['last_restore_test_datetime'] = log.restore_datetime
            if log.status == 'success':
                vals['restore_test_status'] = 'success'
            elif log.status == 'warning':
                vals['restore_test_status'] = 'warning'
            else:
                vals['restore_test_status'] = 'failed'
        history.write(vals)

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
