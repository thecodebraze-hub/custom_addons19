# -*- coding: utf-8 -*-
import errno
import hashlib
import logging
import stat
from contextlib import contextmanager
from io import StringIO
from pathlib import Path

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    BackupError,
    SFTP_UPLOAD_SUFFIX,
    backup_datetime_from_sources,
    identify_managed_backup_from_fileobj,
    is_our_backup_filename,
    is_sftp_path_inside,
    is_temporary_backup_filename,
    join_sftp_path,
    normalize_sftp_root,
    normalize_ssh_fingerprint,
    sanitize_error_message,
    sanitize_relative_dir,
)

from .base import BaseStorageProvider, ListBackupsResult, ListedBackup, StorageResult

_logger = logging.getLogger(__name__)

SFTP_CONNECT_TIMEOUT = 30
SFTP_BANNER_TIMEOUT = 30
SFTP_AUTH_TIMEOUT = 30
SFTP_TRANSFER_CHUNK = 1024 * 1024


class FingerprintHostKeyPolicy:
    """Reject unknown SSH hosts unless the configured fingerprint matches."""

    def __init__(self, expected_fingerprint=''):
        self.expected_fingerprint = (expected_fingerprint or '').strip()
        self.remote_fingerprint = ''

    def missing_host_key(self, client, hostname, key):
        self.remote_fingerprint = format_ssh_key_fingerprint(key)
        if not self.expected_fingerprint:
            raise BackupError(
                'SFTP host key is not configured. Remote fingerprint: %s. '
                'Verify this fingerprint out-of-band, then save it on the storage destination.'
                % self.remote_fingerprint
            )
        if not ssh_fingerprint_matches(self.expected_fingerprint, key):
            raise BackupError(
                'SFTP host key does not match the configured fingerprint. '
                'Remote fingerprint: %s.' % self.remote_fingerprint
            )
        client.get_host_keys().add(hostname, key.get_name(), key)


def format_ssh_key_fingerprint(key):
    digest = hashlib.sha256(key.asbytes()).digest()
    import base64
    return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')


def ssh_fingerprint_matches(expected, key):
    expected_n = normalize_ssh_fingerprint(expected)
    if not expected_n:
        return False
    raw = key.asbytes()
    sha256 = hashlib.sha256(raw).digest()
    md5 = hashlib.md5(raw, usedforsecurity=False).digest()
    import base64
    candidates = (
        'SHA256:' + base64.b64encode(sha256).decode('ascii').rstrip('='),
        sha256.hex(),
        ':'.join('%02x' % byte for byte in md5),
        md5.hex(),
    )
    return any(normalize_ssh_fingerprint(candidate) == expected_n for candidate in candidates)


class SftpStorageProvider(BaseStorageProvider):
    provider_type = 'sftp'

    def validate(self, connect=True):
        self._validate_configuration()
        if not connect:
            return self._remote_root()
        return self.test_connection()

    def test_connection(self):
        self._validate_configuration()
        with self._session() as sftp:
            root = self._remote_root()
            self._require_remote_directory(sftp, root, create=False)
            self._assert_remote_writable(sftp, root)
        return root

    def store(self, zip_path, filename, relative_dir=''):
        destination = self._safe_destination_label()
        temp_remote = ''
        try:
            self._validate_configuration()
            zip_path = Path(zip_path)
            safe_name = Path(filename).name
            if safe_name != filename or not (
                safe_name.endswith('.zip') or safe_name.endswith('.enc')
            ):
                raise BackupError('Backup filename is invalid.')
            local_size = zip_path.stat().st_size
            dest_dir = self._destination_dir(relative_dir)
            final_remote = join_sftp_path(dest_dir, safe_name)
            temp_remote = final_remote + SFTP_UPLOAD_SUFFIX

            with self._session() as sftp:
                self._require_remote_directory(sftp, self._remote_root(), create=False)
                self._ensure_remote_directory(sftp, dest_dir)
                self._remove_if_exists(sftp, temp_remote)
                self._stream_upload(sftp, zip_path, temp_remote)
                remote_size = int(sftp.stat(temp_remote).st_size)
                if remote_size != local_size:
                    self._remove_if_exists(sftp, temp_remote)
                    raise BackupError(
                        'SFTP remote file size does not match the local backup size.'
                    )
                self._replace_remote(sftp, temp_remote, final_remote)
                verified_size = int(sftp.stat(final_remote).st_size)
                if verified_size != local_size:
                    self._remove_if_exists(sftp, final_remote)
                    raise BackupError(
                        'SFTP remote file verification failed after rename.'
                    )
                temp_remote = ''

            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=final_remote,
                file_size=verified_size,
                metadata=self._result_metadata(),
            )
        except BackupError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=sanitize_error_message(str(exc)),
                metadata=self._result_metadata(),
            )
        except Exception as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=self._safe_sftp_error(exc),
                metadata=self._result_metadata(),
            )
        finally:
            if temp_remote:
                try:
                    with self._session() as sftp:
                        self._remove_if_exists(sftp, temp_remote)
                except Exception:
                    _logger.warning(
                        'Unable to clean up partial SFTP upload at destination %s.',
                        destination,
                    )

    def list_backups(self, relative_dir='', database_name=None, plan_id=None):
        destination = self._safe_destination_label()
        try:
            self._validate_configuration()
            dest_dir = self._destination_dir(relative_dir)
            files = []
            with self._session() as sftp:
                if not self._remote_exists(sftp, dest_dir):
                    return ListBackupsResult(
                        success=True,
                        destination=destination,
                        files=[],
                        metadata=self._result_metadata(),
                    )
                for entry in sftp.listdir_attr(dest_dir):
                    listed = self._inspect_remote_entry(
                        sftp, dest_dir, entry, database_name, plan_id,
                    )
                    if listed:
                        files.append(listed)
            return ListBackupsResult(
                success=True,
                destination=destination,
                files=files,
                metadata=self._result_metadata(),
            )
        except BackupError as exc:
            return ListBackupsResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=sanitize_error_message(str(exc)),
                metadata=self._result_metadata(),
            )
        except Exception as exc:
            return ListBackupsResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=self._safe_sftp_error(exc),
                metadata=self._result_metadata(),
            )

    def delete_backup(self, file_path):
        destination = self._safe_destination_label()
        try:
            self._validate_configuration()
            root = self._remote_root()
            remote = (file_path or '').replace('\\', '/')
            if not is_sftp_path_inside(root, remote):
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Path is outside the configured backup directory.',
                    metadata=self._result_metadata(),
                )
            filename = remote.rstrip('/').rsplit('/', 1)[-1]
            if is_temporary_backup_filename(filename):
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Refusing to delete a temporary file via retention.',
                    metadata=self._result_metadata(),
                )
            with self._session() as sftp:
                attrs = self._stat_or_none(sftp, remote)
                if attrs is None:
                    return StorageResult(
                        success=False,
                        destination=destination,
                        status='skipped',
                        error_message='Target is not a file or no longer exists.',
                        metadata=self._result_metadata(),
                    )
                if stat.S_ISDIR(attrs.st_mode):
                    return StorageResult(
                        success=False,
                        destination=destination,
                        status='skipped',
                        error_message='Refusing to delete a directory.',
                        metadata=self._result_metadata(),
                    )
                file_size = int(getattr(attrs, 'st_size', 0) or 0)
                sftp.remove(remote)
            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=remote,
                file_size=file_size,
                metadata=self._result_metadata(),
            )
        except BackupError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=sanitize_error_message(str(exc)),
                metadata=self._result_metadata(),
            )
        except Exception as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=self._safe_sftp_error(exc),
                metadata=self._result_metadata(),
            )

    def download_backup(self, remote_path, local_path):
        destination = self._safe_destination_label()
        try:
            self._validate_configuration()
            root = self._remote_root()
            remote = (remote_path or '').replace('\\', '/')
            if not is_sftp_path_inside(root, remote):
                raise BackupError('Backup file path is outside the configured remote directory.')
            target = Path(local_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with self._session() as sftp:
                attrs = self._stat_or_none(sftp, remote)
                if attrs is None:
                    raise BackupError('Backup file does not exist.')
                if stat.S_ISDIR(attrs.st_mode):
                    raise BackupError('Remote backup path is a directory.')
                if stat.S_ISLNK(getattr(attrs, 'st_mode', 0) or 0):
                    raise BackupError('Refusing to download a remote symlink.')
                remote_size = int(getattr(attrs, 'st_size', 0) or 0)
                self._stream_download(sftp, remote, target)
                local_size = target.stat().st_size
                if remote_size and local_size != remote_size:
                    raise BackupError('Downloaded backup size does not match the remote file.')
            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=str(target),
                file_size=target.stat().st_size,
                metadata=self._result_metadata(),
            )
        except BackupError as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=sanitize_error_message(str(exc)),
                metadata=self._result_metadata(),
            )
        except Exception as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=self._safe_sftp_error(exc),
                metadata=self._result_metadata(),
            )

    def _stream_download(self, sftp, remote_path, local_path):
        with sftp.open(remote_path, 'rb') as source, Path(local_path).open('wb') as target:
            while True:
                chunk = source.read(SFTP_TRANSFER_CHUNK)
                if not chunk:
                    break
                target.write(chunk)
            target.flush()

    def _validate_configuration(self):
        storage = self.storage.sudo()
        if not (storage.sftp_host or '').strip():
            raise BackupError('SFTP host is required.')
        host = storage.sftp_host.strip()
        if any(char.isspace() for char in host) or '/' in host or '\\' in host:
            raise BackupError('SFTP host is invalid.')
        port = storage.sftp_port or 0
        if port < 1 or port > 65535:
            raise BackupError('SFTP port must be between 1 and 65535.')
        if not (storage.sftp_username or '').strip():
            raise BackupError('SFTP username is required.')
        auth_type = storage.sftp_authentication_type or 'password'
        if auth_type == 'password':
            if not storage.sftp_password:
                raise BackupError('SFTP password is required for password authentication.')
        elif auth_type == 'private_key':
            if not (storage.sftp_private_key or '').strip():
                raise BackupError('SFTP private key is required for private-key authentication.')
        else:
            raise BackupError('SFTP authentication type is invalid.')
        normalize_sftp_root(storage.sftp_remote_path)

    def _remote_root(self):
        return normalize_sftp_root(self.storage.sudo().sftp_remote_path)

    def _destination_dir(self, relative_dir):
        return join_sftp_path(self._remote_root(), sanitize_relative_dir(relative_dir))

    @contextmanager
    def _session(self):
        ssh = None
        sftp = None
        try:
            ssh, sftp = self._open_session()
            yield sftp
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if ssh is not None:
                try:
                    ssh.close()
                except Exception:
                    pass

    def _open_session(self):
        paramiko = self._require_paramiko()
        storage = self.storage.sudo()
        client = paramiko.SSHClient()
        policy = FingerprintHostKeyPolicy(storage.sftp_host_key)
        client.set_missing_host_key_policy(policy)
        connect_kwargs = {
            'hostname': storage.sftp_host.strip(),
            'port': storage.sftp_port or 22,
            'username': storage.sftp_username.strip(),
            'timeout': SFTP_CONNECT_TIMEOUT,
            'banner_timeout': SFTP_BANNER_TIMEOUT,
            'auth_timeout': SFTP_AUTH_TIMEOUT,
            'allow_agent': False,
            'look_for_keys': False,
        }
        auth_type = storage.sftp_authentication_type or 'password'
        try:
            if auth_type == 'private_key':
                connect_kwargs['pkey'] = self._load_private_key(paramiko, storage)
            else:
                connect_kwargs['password'] = storage.sftp_password
            client.connect(**connect_kwargs)
            sftp = client.open_sftp()
            try:
                channel = sftp.get_channel()
                if channel is not None:
                    channel.settimeout(SFTP_CONNECT_TIMEOUT)
            except Exception:
                pass
            return client, sftp
        except BackupError:
            try:
                client.close()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            raise BackupError(self._safe_sftp_error(exc, policy)) from exc

    def _load_private_key(self, paramiko, storage):
        key_material = (storage.sftp_private_key or '').strip()
        passphrase = storage.sftp_private_key_passphrase or None
        errors = []
        for key_cls in (
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
            paramiko.RSAKey,
            getattr(paramiko, 'DSSKey', paramiko.RSAKey),
        ):
            try:
                return key_cls.from_private_key(StringIO(key_material), password=passphrase)
            except Exception as exc:
                errors.append(exc)
                continue
        raise BackupError('SFTP private key could not be loaded. Check the key format and passphrase.')

    def _require_paramiko(self):
        try:
            import paramiko
            return paramiko
        except ImportError as exc:
            raise BackupError(
                'SFTP storage requires the Paramiko Python library. '
                'Install it with: pip install paramiko'
            ) from exc

    def _stream_upload(self, sftp, zip_path, remote_path):
        with zip_path.open('rb') as source, sftp.open(remote_path, 'wb') as target:
            while True:
                chunk = source.read(SFTP_TRANSFER_CHUNK)
                if not chunk:
                    break
                target.write(chunk)
            if hasattr(target, 'flush'):
                target.flush()

    def _replace_remote(self, sftp, temp_remote, final_remote):
        self._remove_if_exists(sftp, final_remote)
        if hasattr(sftp, 'posix_rename'):
            try:
                sftp.posix_rename(temp_remote, final_remote)
                return
            except Exception:
                pass
        if hasattr(sftp, 'rename'):
            sftp.rename(temp_remote, final_remote)
            return
        raise BackupError('SFTP server does not support renaming the uploaded file.')

    def _require_remote_directory(self, sftp, remote_dir, create=False):
        attrs = self._stat_or_none(sftp, remote_dir)
        if attrs is None:
            if create:
                sftp.mkdir(remote_dir)
                return
            raise BackupError('SFTP remote directory "%s" does not exist.' % remote_dir)
        if not stat.S_ISDIR(attrs.st_mode):
            raise BackupError('SFTP remote path is not a directory: %s' % remote_dir)

    def _ensure_remote_directory(self, sftp, remote_dir):
        root = self._remote_root()
        if remote_dir != root and not is_sftp_path_inside(root, remote_dir):
            raise BackupError('SFTP path is outside the configured remote directory.')
        self._require_remote_directory(sftp, root, create=False)
        relative = remote_dir[len(root):].strip('/')
        current = root
        if not relative:
            return
        for part in relative.split('/'):
            current = '%s/%s' % (current.rstrip('/'), part)
            attrs = self._stat_or_none(sftp, current)
            if attrs is None:
                sftp.mkdir(current)
            elif not stat.S_ISDIR(attrs.st_mode):
                raise BackupError('SFTP path is not a directory: %s' % current)

    def _assert_remote_writable(self, sftp, remote_dir):
        probe = join_sftp_path(remote_dir, '.cb_backup_write_test')
        try:
            with sftp.open(probe, 'wb') as handle:
                handle.write(b'ok')
            sftp.remove(probe)
        except Exception as exc:
            raise BackupError(
                'SFTP remote directory "%s" is not writable.' % remote_dir
            ) from exc

    def _inspect_remote_entry(self, sftp, dest_dir, entry, database_name, plan_id):
        filename = getattr(entry, 'filename', '') or ''
        remote_path = join_sftp_path(dest_dir, filename)
        mode = getattr(entry, 'st_mode', 0) or 0
        if stat.S_ISLNK(mode):
            return ListedBackup(
                path=remote_path,
                filename=filename,
                skip_reason='Skipped symlink.',
            )
        if stat.S_ISDIR(mode):
            return None
        if not is_sftp_path_inside(self._remote_root(), remote_path):
            return ListedBackup(
                path=remote_path,
                filename=filename,
                skip_reason='Path is outside the configured backup directory.',
            )
        if is_temporary_backup_filename(filename):
            return ListedBackup(
                path=remote_path,
                filename=filename,
                skip_reason='Temporary or hidden file.',
            )
        if database_name and not is_our_backup_filename(filename, database_name):
            return ListedBackup(
                path=remote_path,
                filename=filename,
                skip_reason='Filename does not match managed backup pattern.',
            )
        size = int(getattr(entry, 'st_size', 0) or 0)
        identified = False
        manifest = None
        skip_reason = 'Filename does not match managed backup pattern.'
        try:
            with sftp.open(remote_path, 'rb') as handle:
                identified, manifest, skip_reason = identify_managed_backup_from_fileobj(
                    handle,
                    filename,
                    database_name,
                    plan_id=plan_id,
                    require_plan_id=False,
                )
        except Exception as exc:
            identified = False
            skip_reason = 'Unable to inspect remote file: %s' % self._safe_sftp_error(exc)
        backup_dt = backup_datetime_from_sources(manifest, filename) if identified else None
        return ListedBackup(
            path=remote_path,
            filename=filename,
            size=size,
            backup_datetime=backup_dt,
            database_name=(manifest or {}).get('database_name') or '',
            plan_id=int((manifest or {}).get('plan_id') or 0),
            identified=identified,
            skip_reason='' if identified else skip_reason,
        )

    def _remove_if_exists(self, sftp, remote_path):
        if self._stat_or_none(sftp, remote_path) is not None:
            sftp.remove(remote_path)

    def _remote_exists(self, sftp, remote_path):
        return self._stat_or_none(sftp, remote_path) is not None

    def _stat_or_none(self, sftp, remote_path):
        try:
            return sftp.stat(remote_path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if getattr(exc, 'errno', None) in (errno.ENOENT, 2):
                return None
            raise

    def _safe_sftp_error(self, exc, policy=None):
        paramiko = None
        try:
            import paramiko
        except ImportError:
            paramiko = None
        if isinstance(exc, BackupError):
            return sanitize_error_message(str(exc))
        if paramiko and isinstance(exc, paramiko.AuthenticationException):
            return 'SFTP authentication failed.'
        if paramiko and isinstance(exc, paramiko.BadHostKeyException):
            return 'SFTP host key does not match the configured fingerprint.'
        if paramiko and isinstance(exc, paramiko.SSHException):
            message = str(exc).lower()
            if 'not in the list of known hosts' in message or 'host key' in message:
                fingerprint = getattr(policy, 'remote_fingerprint', '') if policy else ''
                if fingerprint:
                    return (
                        'SFTP host key is not configured. Remote fingerprint: %s. '
                        'Verify this fingerprint out-of-band, then save it on the storage destination.'
                        % fingerprint
                    )
                return 'SFTP host key verification failed.'
            if 'no existing session' in message or 'not connected' in message:
                return 'SFTP connection was dropped.'
            return 'SFTP connection failed.'
        if isinstance(exc, TimeoutError):
            return 'SFTP connection timed out.'
        if isinstance(exc, OSError):
            err = getattr(exc, 'errno', None)
            if err in (errno.EACCES, 13):
                return 'SFTP permission denied.'
            if err in (errno.ENOSPC, 28):
                return 'SFTP remote disk is full.'
            if err in (errno.ECONNRESET, errno.EPIPE, 104, 32):
                return 'SFTP connection was dropped.'
            unknown_host = getattr(errno, 'EAI_NONAME', None)
            if (unknown_host is not None and err == unknown_host) or err == -2 or 'getaddrinfo' in str(exc).lower():
                return 'SFTP host could not be resolved.'
            if 'timed out' in str(exc).lower():
                return 'SFTP connection timed out.'
        return sanitize_error_message(str(exc) or 'SFTP operation failed.')
