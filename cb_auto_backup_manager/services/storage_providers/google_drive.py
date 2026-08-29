# -*- coding: utf-8 -*-
import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    BackupError,
    backup_datetime_from_sources,
    is_our_backup_filename,
    is_temporary_backup_filename,
    sanitize_error_message,
    sanitize_relative_dir,
)

from .base import BaseStorageProvider, ListBackupsResult, ListedBackup, StorageResult

_logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_DRIVE_API = 'https://www.googleapis.com/drive/v3'
GOOGLE_UPLOAD_API = 'https://www.googleapis.com/upload/drive/v3/files'
GOOGLE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
GOOGLE_FOLDER_MIME = 'application/vnd.google-apps.folder'
GOOGLE_CONNECT_TIMEOUT = 30
GOOGLE_READ_TIMEOUT = 120
GOOGLE_UPLOAD_TIMEOUT = 600
GOOGLE_CHUNK_SIZE = 8 * 1024 * 1024
GOOGLE_FILE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{10,256}$')
APP_PROPERTY_MODULE = 'cb_auto_backup_manager'
REQUESTS_CONNECT_ERROR = (
    'ConnectionError', 'Timeout', 'ReadTimeout', 'ConnectTimeout', 'SSLError',
)


class GoogleDriveStorageProvider(BaseStorageProvider):
    provider_type = 'google_drive'

    def validate(self, connect=True):
        self._validate_configuration(require_token=connect)
        if not connect:
            return True
        return self.test_connection()

    def test_connection(self):
        self._validate_configuration(require_token=True)
        account = self._request_json('GET', '%s/about' % GOOGLE_DRIVE_API, params={
            'fields': 'user(emailAddress,displayName)',
        })
        email = ((account or {}).get('user') or {}).get('emailAddress') or ''
        folder_id = self._ensure_root_folder()
        write_vals = {
            'google_drive_folder_id': folder_id,
            'google_drive_connection_status': 'connected',
        }
        if email:
            write_vals['google_drive_account'] = email
        self._write_storage(write_vals)
        return folder_id

    def store(self, zip_path, filename, relative_dir=''):
        destination = self._safe_destination_label()
        try:
            self._validate_configuration(require_token=True)
            zip_path = Path(zip_path)
            safe_name = Path(filename).name
            if safe_name != filename or not (
                safe_name.endswith('.zip') or safe_name.endswith('.enc')
            ):
                raise BackupError('Backup filename is invalid.')
            local_size = zip_path.stat().st_size
            self._last_relative_dir = relative_dir
            parent_id = self._ensure_folder_path(relative_dir)
            file_id = self._resumable_upload(
                zip_path,
                safe_name,
                parent_id,
                local_size,
            )
            meta = self._get_file(file_id, fields='id,name,size')
            remote_size = int(meta.get('size') or 0)
            if remote_size and remote_size != local_size:
                self._trash_file(file_id)
                raise BackupError(
                    'Google Drive remote file size does not match the local backup size.'
                )
            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=format_google_drive_file_ref(file_id),
                file_size=remote_size or local_size,
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
                error_message=self._safe_drive_error(exc),
                metadata=self._result_metadata(),
            )

    def list_backups(self, relative_dir='', database_name=None, plan_id=None):
        destination = self._safe_destination_label()
        try:
            self._validate_configuration(require_token=True)
            parent_id = self._find_folder_path(relative_dir)
            if not parent_id:
                return ListBackupsResult(
                    success=True,
                    destination=destination,
                    files=[],
                    metadata=self._result_metadata(),
                )
            files = []
            for entry in self._list_children(parent_id):
                listed = self._inspect_entry(entry, database_name, plan_id)
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
                error_message=self._safe_drive_error(exc),
                metadata=self._result_metadata(),
            )

    def delete_backup(self, file_path):
        destination = self._safe_destination_label()
        try:
            self._validate_configuration(require_token=True)
            file_id = parse_google_drive_file_ref(file_path)
            meta = self._get_file(file_id, fields='id,name,size,trashed,appProperties,mimeType')
            if meta.get('trashed'):
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Target is not a file or no longer exists.',
                    metadata=self._result_metadata(),
                )
            if meta.get('mimeType') == GOOGLE_FOLDER_MIME:
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Refusing to delete a directory.',
                    metadata=self._result_metadata(),
                )
            filename = meta.get('name') or ''
            if is_temporary_backup_filename(filename):
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Refusing to delete a temporary file via retention.',
                    metadata=self._result_metadata(),
                )
            properties = meta.get('appProperties') or {}
            if properties.get('cb_module') != APP_PROPERTY_MODULE:
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='File was not created by this module.',
                    metadata=self._result_metadata(),
                )
            if not is_our_backup_filename(filename):
                return StorageResult(
                    success=False,
                    destination=destination,
                    status='skipped',
                    error_message='Filename does not match managed backup pattern.',
                    metadata=self._result_metadata(),
                )
            file_size = int(meta.get('size') or 0)
            self._trash_file(file_id)
            return StorageResult(
                success=True,
                destination=destination,
                status='success',
                final_path=format_google_drive_file_ref(file_id),
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
                error_message=self._safe_drive_error(exc),
                metadata=self._result_metadata(),
            )

    def download_backup(self, remote_path, local_path):
        destination = self._safe_destination_label()
        try:
            self._validate_configuration(require_token=True)
            file_id = parse_google_drive_file_ref(remote_path)
            meta = self._get_file(file_id, fields='id,name,size,trashed,mimeType')
            if meta.get('trashed') or meta.get('mimeType') == GOOGLE_FOLDER_MIME:
                raise BackupError('Backup file does not exist.')
            target = Path(local_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            expected = int(meta.get('size') or 0)
            self._download_media(file_id, target)
            file_size = target.stat().st_size
            if expected and file_size != expected:
                raise BackupError('Downloaded Google Drive file size does not match the remote file.')
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
                error_message=sanitize_error_message(str(exc)),
                metadata=self._result_metadata(),
            )
        except Exception as exc:
            return StorageResult(
                success=False,
                destination=destination,
                status='failed',
                error_message=self._safe_drive_error(exc),
                metadata=self._result_metadata(),
            )

    def authorization_url(self, redirect_uri, state):
        self._validate_configuration(require_token=False)
        params = {
            'client_id': (self.storage.google_drive_client_id or '').strip(),
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': GOOGLE_SCOPE,
            'access_type': 'offline',
            'prompt': 'consent',
            'include_granted_scopes': 'true',
            'state': state,
        }
        return '%s?%s' % (GOOGLE_AUTH_URL, urlencode(params))

    def exchange_authorization_code(self, code, redirect_uri):
        self._validate_configuration(require_token=False)
        payload = self._token_request({
            'code': (code or '').strip(),
            'client_id': (self.storage.google_drive_client_id or '').strip(),
            'client_secret': self._client_secret(),
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        })
        refresh = payload.get('refresh_token')
        access = payload.get('access_token')
        if not refresh:
            raise BackupError(
                'Google did not return a refresh token. Revoke this app in the Google account, '
                'then connect again so offline access can be granted.'
            )
        if not access:
            raise BackupError('Google authorization did not return an access token.')
        self._persist_tokens(access, refresh, payload.get('expires_in'))
        self.test_connection()

    def _validate_configuration(self, require_token=True):
        if not (self.storage.google_drive_client_id or '').strip():
            raise BackupError('Google Drive Client ID is required.')
        if not self._client_secret():
            raise BackupError('Google Drive Client Secret is required.')
        folder = (self.storage.google_drive_folder or '').strip() or 'Odoo Backups'
        if '/' in folder or '\\' in folder or folder in ('.', '..'):
            raise BackupError('Google Drive folder name must not contain path separators.')
        if require_token and not self._refresh_token():
            raise BackupError(
                'Google Drive is not authorized. Use Connect Google Drive, then Test Connection.'
            )

    def _ensure_root_folder(self):
        name = (self.storage.google_drive_folder or '').strip() or 'Odoo Backups'
        existing = (self.storage.google_drive_folder_id or '').strip()
        if existing:
            try:
                meta = self._get_file(existing, fields='id,name,mimeType,trashed')
                if not meta.get('trashed') and meta.get('mimeType') == GOOGLE_FOLDER_MIME:
                    return existing
            except BackupError:
                pass
        found = self._find_child_folder('root', name)
        folder_id = found or self._create_folder(name, 'root')
        if folder_id != existing:
            self._write_storage({'google_drive_folder_id': folder_id})
        return folder_id

    def _ensure_folder_path(self, relative_dir):
        folder_id = self._ensure_root_folder()
        rel = sanitize_relative_dir(relative_dir)
        if not rel:
            return folder_id
        current = folder_id
        for part in rel.replace('\\', '/').split('/'):
            if not part or part in ('.', '..'):
                continue
            found = self._find_child_folder(current, part)
            current = found or self._create_folder(part, current)
        return current

    def _find_folder_path(self, relative_dir):
        root_id = (self.storage.google_drive_folder_id or '').strip()
        if not root_id:
            try:
                root_id = self._ensure_root_folder()
            except BackupError:
                return ''
        rel = sanitize_relative_dir(relative_dir)
        if not rel:
            return root_id
        current = root_id
        for part in rel.replace('\\', '/').split('/'):
            if not part or part in ('.', '..'):
                continue
            current = self._find_child_folder(current, part)
            if not current:
                return ''
        return current

    def _find_child_folder(self, parent_id, name):
        safe_name = (name or '').replace("'", "\\'")
        query = (
            "name='%s' and mimeType='%s' and trashed=false and '%s' in parents"
            % (safe_name, GOOGLE_FOLDER_MIME, parent_id)
        )
        payload = self._request_json('GET', '%s/files' % GOOGLE_DRIVE_API, params={
            'q': query,
            'spaces': 'drive',
            'fields': 'files(id,name)',
            'pageSize': 5,
        })
        files = payload.get('files') or []
        return files[0]['id'] if files else ''

    def _create_folder(self, name, parent_id):
        payload = self._request_json('POST', '%s/files' % GOOGLE_DRIVE_API, json_body={
            'name': name,
            'mimeType': GOOGLE_FOLDER_MIME,
            'parents': [parent_id],
            'appProperties': {'cb_module': APP_PROPERTY_MODULE},
        })
        folder_id = payload.get('id')
        if not folder_id:
            raise BackupError('Google Drive folder could not be created.')
        return folder_id

    def _list_children(self, parent_id):
        files = []
        page_token = ''
        while True:
            params = {
                'q': "'%s' in parents and trashed=false" % parent_id,
                'spaces': 'drive',
                'fields': 'nextPageToken,files(id,name,size,createdTime,appProperties,mimeType)',
                'pageSize': 200,
            }
            if page_token:
                params['pageToken'] = page_token
            payload = self._request_json('GET', '%s/files' % GOOGLE_DRIVE_API, params=params)
            files.extend(payload.get('files') or [])
            page_token = payload.get('nextPageToken') or ''
            if not page_token:
                break
        return files

    def _inspect_entry(self, entry, database_name, plan_id):
        filename = entry.get('name') or ''
        file_id = entry.get('id') or ''
        mime = entry.get('mimeType') or ''
        if mime == GOOGLE_FOLDER_MIME:
            return None
        path = format_google_drive_file_ref(file_id)
        size = int(entry.get('size') or 0)
        properties = entry.get('appProperties') or {}
        if is_temporary_backup_filename(filename):
            return ListedBackup(path=path, filename=filename, skip_reason='Temporary or hidden file.')
        if properties.get('cb_module') != APP_PROPERTY_MODULE:
            return ListedBackup(
                path=path,
                filename=filename,
                size=size,
                skip_reason='File was not created by this module.',
            )
        identified, manifest, skip_reason = _match_drive_properties(
            properties, filename, database_name, plan_id,
        )
        backup_dt = backup_datetime_from_sources(manifest, filename, None) if identified else None
        return ListedBackup(
            path=path,
            filename=filename,
            size=size,
            backup_datetime=backup_dt,
            database_name=properties.get('cb_database') or '',
            plan_id=int(properties.get('cb_plan_id') or 0),
            identified=identified,
            skip_reason='' if identified else skip_reason,
        )

    def _resumable_upload(self, zip_path, filename, parent_id, file_size):
        properties = {
            'cb_module': APP_PROPERTY_MODULE,
            'cb_database': _safe_app_property(self.storage.env.cr.dbname),
        }
        plan_id = _plan_id_from_relative(getattr(self, '_last_relative_dir', ''))
        if plan_id:
            properties['cb_plan_id'] = str(plan_id)
        metadata = {
            'name': filename,
            'parents': [parent_id],
            'appProperties': properties,
        }
        headers = {
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': 'application/octet-stream',
            'X-Upload-Content-Length': str(int(file_size)),
        }
        session = self._request(
            'POST',
            '%s?uploadType=resumable' % GOOGLE_UPLOAD_API,
            headers=headers,
            json_body=metadata,
            raw=True,
        )
        location = session.headers.get('Location') or session.headers.get('location')
        if not location:
            raise BackupError('Google Drive did not start a resumable upload session.')
        offset = 0
        file_id = ''
        with zip_path.open('rb') as handle:
            while offset < file_size:
                chunk = handle.read(GOOGLE_CHUNK_SIZE)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                put_headers = {
                    'Content-Length': str(len(chunk)),
                    'Content-Range': 'bytes %s-%s/%s' % (offset, end, file_size),
                }
                response = self._request(
                    'PUT',
                    location,
                    headers=put_headers,
                    data=chunk,
                    raw=True,
                    retry_unauthorized=False,
                )
                if response.status_code in (200, 201):
                    payload = _json_or_empty(response)
                    file_id = payload.get('id') or ''
                    break
                if response.status_code == 308:
                    offset = end + 1
                    continue
                raise BackupError(self._message_from_response(response))
        if not file_id:
            raise BackupError('Google Drive upload did not return a file id.')
        return file_id

    def _download_media(self, file_id, target):
        response = self._request(
            'GET',
            '%s/files/%s' % (GOOGLE_DRIVE_API, quote(file_id)),
            params={'alt': 'media'},
            raw=True,
            stream=True,
        )
        if response.status_code != 200:
            raise BackupError(self._message_from_response(response))
        with target.open('wb') as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)

    def _get_file(self, file_id, fields='id,name'):
        return self._request_json(
            'GET',
            '%s/files/%s' % (GOOGLE_DRIVE_API, quote(file_id)),
            params={'fields': fields},
        )

    def _trash_file(self, file_id):
        self._request_json(
            'PATCH',
            '%s/files/%s' % (GOOGLE_DRIVE_API, quote(file_id)),
            json_body={'trashed': True},
        )

    def _ensure_access_token(self):
        token = self._access_token()
        expiry = self.storage.google_drive_token_expiry
        now = datetime.utcnow()
        if token and expiry:
            try:
                if expiry > now + timedelta(seconds=60):
                    return token
            except TypeError:
                pass
        if token and not expiry:
            return token
        refresh = self._refresh_token()
        if not refresh:
            raise BackupError('Google Drive is not authorized.')
        payload = self._token_request({
            'client_id': (self.storage.google_drive_client_id or '').strip(),
            'client_secret': self._client_secret(),
            'refresh_token': refresh,
            'grant_type': 'refresh_token',
        })
        access = payload.get('access_token')
        if not access:
            raise BackupError('Google Drive token refresh failed.')
        self._persist_tokens(access, refresh, payload.get('expires_in'))
        return access

    def _persist_tokens(self, access_token, refresh_token, expires_in):
        expiry = False
        try:
            seconds = int(expires_in or 0)
        except (TypeError, ValueError):
            seconds = 0
        if seconds:
            expiry = datetime.utcnow() + timedelta(seconds=max(seconds - 30, 30))
        vals = {
            'google_drive_access_token': access_token or False,
            'google_drive_token_expiry': expiry,
        }
        if refresh_token:
            vals['google_drive_refresh_token'] = refresh_token
        self._write_storage(vals)

    def _write_storage(self, vals):
        self.storage.sudo().write(vals)
        self.storage.invalidate_recordset(tuple(vals))

    def _client_secret(self):
        return (self.storage.sudo().google_drive_client_secret or '').strip()

    def _refresh_token(self):
        return (self.storage.sudo().google_drive_refresh_token or '').strip()

    def _access_token(self):
        return (self.storage.sudo().google_drive_access_token or '').strip()

    def _token_request(self, data):
        response = self._request(
            'POST',
            GOOGLE_TOKEN_URL,
            data=data,
            raw=True,
            authorize=False,
            retry_unauthorized=False,
        )
        if response.status_code >= 400:
            raise BackupError(self._message_from_response(response, fallback='Google authorization failed.'))
        payload = _json_or_empty(response)
        if not payload:
            raise BackupError('Google authorization returned an empty response.')
        return payload

    def _request_json(self, method, url, **kwargs):
        response = self._request(method, url, raw=True, **kwargs)
        if response.status_code >= 400:
            raise BackupError(self._message_from_response(response))
        return _json_or_empty(response)

    def _request(
        self,
        method,
        url,
        params=None,
        headers=None,
        json_body=None,
        data=None,
        raw=False,
        stream=False,
        authorize=True,
        retry_unauthorized=True,
        timeout=None,
    ):
        requests = _require_requests()
        hdrs = dict(headers or {})
        if authorize:
            hdrs['Authorization'] = 'Bearer %s' % self._ensure_access_token()
        if json_body is not None:
            if data is None:
                data = json.dumps(json_body)
            if not any(key.lower() == 'content-type' for key in hdrs):
                hdrs['Content-Type'] = 'application/json; charset=UTF-8'
        kwargs = {
            'params': params,
            'headers': hdrs,
            'data': data,
            'timeout': timeout or (GOOGLE_CONNECT_TIMEOUT, GOOGLE_READ_TIMEOUT),
            'stream': stream,
        }
        last_error = None
        for attempt in range(3):
            try:
                response = requests.request(method, url, **kwargs)
            except Exception as exc:
                last_error = exc
                if type(exc).__name__ in REQUESTS_CONNECT_ERROR and attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise BackupError(self._safe_drive_error(exc)) from exc
            if response.status_code == 401 and authorize and retry_unauthorized:
                self._write_storage({'google_drive_access_token': False, 'google_drive_token_expiry': False})
                hdrs['Authorization'] = 'Bearer %s' % self._ensure_access_token()
                kwargs['headers'] = hdrs
                retry_unauthorized = False
                continue
            if response.status_code == 429 or (
                response.status_code == 403
                and 'rateLimitExceeded' in (response.text or '')
            ):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            return response
        if last_error:
            raise BackupError(self._safe_drive_error(last_error))
        raise BackupError('Google Drive request failed.')

    def _message_from_response(self, response, fallback='Google Drive request failed.'):
        payload = _json_or_empty(response)
        error = payload.get('error')
        if isinstance(error, dict):
            reason = ''
            errors = error.get('errors') or []
            if errors:
                reason = errors[0].get('reason') or ''
            message = error.get('message') or fallback
            if reason == 'storageQuotaExceeded' or reason == 'quotaExceeded':
                return 'Google Drive storage quota is exceeded.'
            if reason in ('rateLimitExceeded', 'userRateLimitExceeded'):
                return 'Google Drive rate limit reached. Try again later.'
            if reason == 'notFound' or response.status_code == 404:
                return 'Google Drive folder or file was not found.'
            if reason == 'authError' or response.status_code == 401:
                return 'Google Drive authorization failed. Reconnect the destination.'
            if 'insufficient' in (message or '').lower() or response.status_code == 403:
                return 'Google Drive permission was denied. Check the authorized account and folder.'
            return sanitize_error_message(message)
        if isinstance(error, str):
            return sanitize_error_message(error)
        if response.status_code == 404:
            return 'Google Drive folder or file was not found.'
        if response.status_code == 401:
            return 'Google Drive authorization failed. Reconnect the destination.'
        if response.status_code == 403:
            return 'Google Drive permission was denied.'
        return fallback

    def _safe_drive_error(self, exc):
        name = type(exc).__name__
        if name in REQUESTS_CONNECT_ERROR or 'timeout' in name.lower():
            return 'Google Drive connection timed out.'
        return sanitize_error_message(str(exc) or 'Google Drive request failed.')


def format_google_drive_file_ref(file_id):
    return 'gdrive:%s' % file_id


def parse_google_drive_file_ref(value):
    raw = (value or '').strip()
    if raw.startswith('gdrive:'):
        raw = raw.split(':', 1)[1].strip()
    if raw.startswith('//file/'):
        raw = raw[7:]
    if not GOOGLE_FILE_ID_RE.match(raw):
        raise BackupError('Invalid Google Drive file reference.')
    return raw


def _match_drive_properties(properties, filename, database_name, plan_id):
    if not is_our_backup_filename(filename, database_name):
        return False, None, 'Filename does not match managed backup pattern.'
    if properties.get('cb_database') and database_name and properties.get('cb_database') != database_name:
        return False, None, 'File belongs to a different database.'
    stored_plan = properties.get('cb_plan_id')
    if plan_id and stored_plan and str(stored_plan) != str(plan_id):
        return False, None, 'File belongs to a different backup plan.'
    manifest = {
        'module_name': APP_PROPERTY_MODULE,
        'database_name': properties.get('cb_database') or database_name or '',
        'plan_id': int(stored_plan or 0) or None,
    }
    return True, manifest, ''


def _plan_id_from_relative(relative_dir):
    for part in (relative_dir or '').replace('\\', '/').split('/'):
        if part.startswith('plan_') and part[5:].isdigit():
            return int(part[5:])
    return 0


def _safe_app_property(value):
    return (value or '')[:100]


def _json_or_empty(response):
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _require_requests():
    try:
        import requests
    except ImportError as exc:
        raise BackupError('The Python package "requests" is required for Google Drive storage.') from exc
    return requests
