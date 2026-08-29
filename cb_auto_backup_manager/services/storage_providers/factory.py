# -*- coding: utf-8 -*-
from .google_drive import GoogleDriveStorageProvider
from .local import LocalStorageProvider
from .sftp import SftpStorageProvider

_PROVIDER_MAP = {
    'local': LocalStorageProvider,
    'sftp': SftpStorageProvider,
    'google_drive': GoogleDriveStorageProvider,
}


def get_storage_provider(storage_record):
    provider_cls = _PROVIDER_MAP.get(storage_record.type)
    if not provider_cls:
        raise ValueError('Unsupported storage type: %s' % storage_record.type)
    return provider_cls(storage_record)
