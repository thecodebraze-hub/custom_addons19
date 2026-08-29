# -*- coding: utf-8 -*-
import os
import shutil
from pathlib import Path

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    BackupError,
    backup_datetime_from_sources,
    identify_managed_backup,
    is_path_inside,
    sanitize_relative_dir,
    validate_local_storage_path,
)

from .base import BaseStorageProvider, ListBackupsResult, ListedBackup, StorageResult


class LocalStorageProvider(BaseStorageProvider):
    provider_type = 'local'

    def validate(self):
        path = validate_local_storage_path(
            self.storage.local_path,
            create_if_missing=True,
        )
        return str(path)

    def store(self, zip_path, filename, relative_dir=''):
        destination = self._safe_destination_label()
        try:
            dest_dir = self._resolve_destination_dir(relative_dir, create_if_missing=True)
            zip_path = Path(zip_path)
            final_path = dest_dir / Path(filename).name
            if not is_path_inside(dest_dir, final_path):
                raise BackupError('Backup file path is outside the storage directory.')
            temp_path = dest_dir / ('.%s.part' % Path(filename).name)

            shutil.copy2(zip_path, temp_path)
            os.replace(temp_path, final_path)

            file_size = final_path.stat().st_size
            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=str(final_path),
                file_size=file_size,
                metadata=self._result_metadata(),
            )
        except BackupError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=str(exc),
                metadata=self._result_metadata(),
            )
        except OSError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message='Local storage failed: %s' % exc,
                metadata=self._result_metadata(),
            )

    def list_backups(self, relative_dir='', database_name=None, plan_id=None):
        destination = self._safe_destination_label()
        try:
            root = validate_local_storage_path(
                self.storage.local_path,
                create_if_missing=False,
            )
        except BackupError as exc:
            message = str(exc)
            if 'does not exist' in message:
                return ListBackupsResult(
                    success=True,
                    destination=destination,
                    files=[],
                    error_message=message,
                    metadata=self._result_metadata(),
                )
            return ListBackupsResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=message,
                metadata=self._result_metadata(),
            )

        try:
            dest_dir = self._resolve_destination_dir(relative_dir, create_if_missing=False)
        except BackupError as exc:
            if 'does not exist' in str(exc):
                return ListBackupsResult(
                    success=True,
                    destination=destination,
                    files=[],
                    metadata=self._result_metadata(),
                )
            return ListBackupsResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=str(exc),
                metadata=self._result_metadata(),
            )

        files = []
        try:
            entries = list(dest_dir.iterdir())
        except OSError as exc:
            return ListBackupsResult(
                success=False,
                destination=destination,
                status='failed',
                error_message='Unable to list storage directory: %s' % exc,
                metadata=self._result_metadata(),
            )

        for entry in entries:
            listed = self._inspect_entry(entry, root, database_name, plan_id)
            if listed:
                files.append(listed)

        return ListBackupsResult(
            success=True,
            destination=destination,
            files=files,
            metadata=self._result_metadata(),
        )

    def delete_backup(self, file_path):
        destination = self._safe_destination_label()
        try:
            root = validate_local_storage_path(
                self.storage.local_path,
                create_if_missing=False,
            )
            target = Path(file_path)
            if target.is_symlink():
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Skipped symlink for safety.',
                    metadata=self._result_metadata(),
                )
            if not is_path_inside(root, target):
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Path is outside the configured backup directory.',
                    metadata=self._result_metadata(),
                )
            if not target.is_file():
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Target is not a file or no longer exists.',
                    metadata=self._result_metadata(),
                )
            if target.is_dir():
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Refusing to delete a directory.',
                    metadata=self._result_metadata(),
                )
            file_size = target.stat().st_size
            target.unlink()
            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=str(target),
                file_size=file_size,
                metadata=self._result_metadata(),
            )
        except BackupError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=str(exc),
                metadata=self._result_metadata(),
            )
        except OSError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message='Unable to delete backup file: %s' % exc,
                metadata=self._result_metadata(),
            )

    def download_backup(self, remote_path, local_path):
        destination = self._safe_destination_label()
        try:
            root = validate_local_storage_path(
                self.storage.local_path,
                create_if_missing=False,
            )
            source = Path(remote_path)
            if source.is_symlink():
                raise BackupError('Refusing to download a symlink.')
            if not is_path_inside(root, source):
                raise BackupError('Backup file path is outside the storage directory.')
            if not source.is_file():
                raise BackupError('Backup file does not exist.')
            target = Path(local_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            file_size = target.stat().st_size
            if file_size != source.stat().st_size:
                raise BackupError('Local backup copy size does not match the source file.')
            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=str(target),
                file_size=file_size,
                metadata=self._result_metadata(),
            )
        except BackupError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=str(exc),
                metadata=self._result_metadata(),
            )
        except OSError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message='Unable to copy backup file: %s' % exc,
                metadata=self._result_metadata(),
            )

    def _resolve_destination_dir(self, relative_dir, create_if_missing=False):
        root = validate_local_storage_path(
            self.storage.local_path,
            create_if_missing=create_if_missing,
        )
        rel = sanitize_relative_dir(relative_dir)
        if not rel:
            return root
        dest = (root / rel)
        dest_resolved = dest.resolve()
        if not is_path_inside(root, dest_resolved):
            raise BackupError('Storage subdirectory is outside the configured path.')
        if create_if_missing:
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists():
            raise BackupError('Local storage path does not exist: %s' % dest)
        elif not dest.is_dir():
            raise BackupError('Local storage path is not a directory: %s' % dest)
        return dest.resolve()

    def _inspect_entry(self, entry, root, database_name, plan_id):
        try:
            if entry.is_symlink():
                return ListedBackup(
                    path=str(entry),
                    filename=entry.name,
                    skip_reason='Skipped symlink.',
                )
            if not entry.is_file():
                return None
            if not is_path_inside(root, entry):
                return ListedBackup(
                    path=str(entry),
                    filename=entry.name,
                    skip_reason='Path is outside the configured backup directory.',
                )
            size = entry.stat().st_size
            identified, manifest, skip_reason = identify_managed_backup(
                entry,
                database_name,
                plan_id=plan_id,
                require_plan_id=False,
            )
            backup_dt = backup_datetime_from_sources(manifest, entry.name, entry) if identified else None
            return ListedBackup(
                path=str(entry),
                filename=entry.name,
                size=size,
                backup_datetime=backup_dt,
                database_name=(manifest or {}).get('database_name') or '',
                plan_id=int((manifest or {}).get('plan_id') or 0),
                identified=identified,
                skip_reason='' if identified else skip_reason,
            )
        except OSError as exc:
            return ListedBackup(
                path=str(entry),
                filename=entry.name,
                skip_reason='Unable to inspect file: %s' % exc,
            )
