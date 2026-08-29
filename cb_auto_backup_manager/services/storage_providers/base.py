# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class StorageResult:
    """Structured result returned by a storage provider."""

    success: bool
    destination: str
    status: str = 'success'
    final_path: str = ''
    file_size: int = 0
    error_message: str = ''
    started: object = None
    completed: object = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_not_implemented(self):
        return self.status == 'not_implemented'


@dataclass
class ListedBackup:
    """A backup file discovered by a storage provider."""

    path: str
    filename: str
    size: int = 0
    backup_datetime: object = None
    database_name: str = ''
    plan_id: int = 0
    identified: bool = False
    skip_reason: str = ''


@dataclass
class ListBackupsResult:
    """Result of listing backups at a destination."""

    success: bool
    destination: str
    status: str = 'success'
    files: list = field(default_factory=list)
    error_message: str = ''
    metadata: dict = field(default_factory=dict)

    @property
    def is_not_implemented(self):
        return self.status == 'not_implemented'


class BaseStorageProvider(ABC):
    """Abstract storage provider interface."""

    provider_type = None

    def __init__(self, storage_record):
        self.storage = storage_record

    @abstractmethod
    def validate(self):
        """Validate destination configuration."""

    @abstractmethod
    def store(self, zip_path, filename, relative_dir=''):
        """Store a verified backup ZIP and return a StorageResult."""

    def list_backups(self, relative_dir='', database_name=None, plan_id=None):
        """List managed backup files. Default: not implemented."""
        return ListBackupsResult(
            success=False,
            destination=self._safe_destination_label(),
            status='not_implemented',
            error_message=self._not_implemented_message('list'),
            metadata=self._result_metadata(),
        )

    def delete_backup(self, file_path):
        """Delete one managed backup file. Default: not implemented."""
        return StorageResult(
            success=False,
            destination=self._safe_destination_label(),
            status='not_implemented',
            error_message=self._not_implemented_message('delete'),
            metadata=self._result_metadata(),
        )

    def download_backup(self, remote_path, local_path):
        """Copy a backup ZIP to local_path using streaming I/O. Default: not implemented."""
        return StorageResult(
            success=False,
            destination=self._safe_destination_label(),
            status='not_implemented',
            error_message=self._not_implemented_message('download'),
            metadata=self._result_metadata(),
        )

    def _safe_destination_label(self):
        return self.storage.display_name or self.storage.name or self.provider_type

    def _result_metadata(self):
        return {'storage_id': self.storage.id}

    def _not_implemented_message(self, operation):
        return (
            '%s storage %s is not implemented yet. '
            'This destination will be available in a future release.'
            % (self._safe_destination_label(), operation)
        )
