# -*- coding: utf-8 -*-
import json
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    MANIFEST_FILENAME,
    create_backup_zip,
    write_manifest_file,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.google_drive import (
    APP_PROPERTY_MODULE,
    GOOGLE_DRIVE_API,
    GOOGLE_FOLDER_MIME,
    GOOGLE_TOKEN_URL,
    GOOGLE_UPLOAD_API,
    parse_google_drive_file_ref,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, content=b''):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self._content = content
        json_safe = self._json_safe(self._payload) if isinstance(self._payload, dict) else {}
        self.text = json.dumps(json_safe) if isinstance(self._payload, dict) else ''

    def json(self):
        if isinstance(self._payload, dict):
            return self._json_safe(self._payload)
        return {}

    def iter_content(self, chunk_size=1024):
        yield self._content

    @staticmethod
    def _json_safe(payload):
        return {
            key: value
            for key, value in payload.items()
            if not isinstance(value, (bytes, bytearray))
        }


class Timeout(Exception):
    """Mimic requests.Timeout for provider error mapping."""


class FakeGoogleAPI:
    def __init__(self):
        self.files = {}
        self.counter = 0
        self.fail_auth = False
        self.fail_quota = False
        self.fail_timeout = False
        self.refresh_calls = 0
        self.uploads = []

    def next_id(self, prefix='file'):
        self.counter += 1
        return '%s%08dabcdefghijk' % (prefix, self.counter)

    def request(self, method, url, **kwargs):
        if self.fail_timeout:
            raise Timeout('timed out')
        method = (method or 'GET').upper()
        params = kwargs.get('params') or {}
        headers = kwargs.get('headers') or {}
        data = kwargs.get('data')
        if url == GOOGLE_TOKEN_URL:
            return self._token(data)
        if self.fail_auth:
            return FakeResponse(401, {'error': {'message': 'authError', 'errors': [{'reason': 'authError'}]}})
        if method == 'GET' and url.endswith('/about'):
            return FakeResponse(200, {'user': {'emailAddress': 'backup@example.com'}})
        if method == 'GET' and url.startswith('%s/files/' % GOOGLE_DRIVE_API):
            file_id = url.rsplit('/', 1)[-1]
            if params.get('alt') == 'media':
                return self._download(file_id)
            return self._get(file_id)
        if method == 'GET' and url.rstrip('/').endswith('/files'):
            return self._list(params)
        if method == 'POST' and url.startswith(GOOGLE_UPLOAD_API):
            return self._start_upload(self._json_body(kwargs, data))
        if method == 'PUT' and url.startswith('https://upload.example.test/session/'):
            return self._put_upload(data, headers)
        if method == 'POST' and url.rstrip('/').endswith('/files'):
            return self._create(self._json_body(kwargs, data))
        if method == 'PATCH' and url.startswith('%s/files/' % GOOGLE_DRIVE_API):
            file_id = url.rsplit('/', 1)[-1]
            return self._patch(file_id, self._json_body(kwargs, data))
        return FakeResponse(404, {'error': {'message': 'notFound', 'errors': [{'reason': 'notFound'}]}})

    def _token(self, data):
        payload = data if isinstance(data, dict) else {}
        self.refresh_calls += 1
        return FakeResponse(200, {
            'access_token': 'ya29-test-access-token',
            'refresh_token': payload.get('refresh_token') or '1//test-refresh-token',
            'expires_in': 3600,
        })

    def _json_body(self, kwargs, data):
        if isinstance(kwargs.get('json'), dict):
            return kwargs['json']
        if isinstance(data, (bytes, bytearray)):
            try:
                return json.loads(data.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {}
        return {}

    def _get(self, file_id):
        rec = self.files.get(file_id)
        if not rec:
            return FakeResponse(404, {'error': {'message': 'notFound', 'errors': [{'reason': 'notFound'}]}})
        return FakeResponse(200, rec)

    def _list(self, params):
        query = params.get('q') or ''
        parent = ''
        if ' in parents' in query:
            before = query.split(' in parents', 1)[0]
            quoted = before.split("'")
            if len(quoted) >= 2:
                parent = quoted[-2]
        matches = []
        for rec in self.files.values():
            if rec.get('trashed'):
                continue
            parents = rec.get('parents') or []
            if parent and parent not in parents:
                continue
            if "mimeType='%s'" % GOOGLE_FOLDER_MIME in query:
                if rec.get('mimeType') != GOOGLE_FOLDER_MIME:
                    continue
                if "name='" in query:
                    name = query.split("name='", 1)[1].split("'", 1)[0]
                    if rec.get('name') != name:
                        continue
            matches.append({
                'id': rec['id'],
                'name': rec.get('name'),
                'size': rec.get('size'),
                'createdTime': rec.get('createdTime'),
                'appProperties': rec.get('appProperties') or {},
                'mimeType': rec.get('mimeType'),
            })
        return FakeResponse(200, {'files': matches})

    def _create(self, body):
        file_id = self.next_id('fld' if body.get('mimeType') == GOOGLE_FOLDER_MIME else 'file')
        rec = {
            'id': file_id,
            'name': body.get('name'),
            'mimeType': body.get('mimeType') or 'application/octet-stream',
            'parents': list(body.get('parents') or ['root']),
            'appProperties': dict(body.get('appProperties') or {}),
            'size': 0,
            'trashed': False,
            'content': b'',
        }
        self.files[file_id] = rec
        return FakeResponse(200, rec)

    def _start_upload(self, body):
        session = 'https://upload.example.test/session/%s' % self.next_id('up')
        self.uploads.append({'id': session, 'buffer': BytesIO(), 'meta': body or {}})
        return FakeResponse(200, {}, headers={'Location': session})

    def _put_upload(self, data, headers):
        if self.fail_quota:
            return FakeResponse(403, {
                'error': {'message': 'quota', 'errors': [{'reason': 'storageQuotaExceeded'}]},
            })
        chunk = data if isinstance(data, (bytes, bytearray)) else b''
        session = self.uploads[-1] if self.uploads else None
        if session:
            session['buffer'].write(chunk)
        content_range = (headers or {}).get('Content-Range') or ''
        total = int(content_range.rsplit('/', 1)[-1]) if '/' in content_range else len(chunk)
        received = session['buffer'].tell() if session else len(chunk)
        if received < total:
            return FakeResponse(308, {}, headers={'Range': 'bytes=0-%s' % (received - 1)})
        content = session['buffer'].getvalue() if session else chunk
        meta = (session or {}).get('meta') or {}
        file_id = self.next_id('bin')
        rec = {
            'id': file_id,
            'name': meta.get('name') or 'uploaded',
            'mimeType': 'application/octet-stream',
            'parents': list(meta.get('parents') or []),
            'appProperties': dict(meta.get('appProperties') or {'cb_module': APP_PROPERTY_MODULE}),
            'size': str(len(content)),
            'trashed': False,
            'content': content,
        }
        self.files[file_id] = rec
        return FakeResponse(200, rec)

    def _download(self, file_id):
        rec = self.files.get(file_id)
        if not rec:
            return FakeResponse(404, {'error': {'message': 'notFound'}})
        return FakeResponse(200, {}, content=rec.get('content') or b'')

    def _patch(self, file_id, body):
        rec = self.files.get(file_id)
        if not rec:
            return FakeResponse(404, {'error': {'message': 'notFound'}})
        rec.update(body)
        return FakeResponse(200, rec)


class FakeRequests:
    def __init__(self, api):
        self.api = api

    def request(self, method, url, **kwargs):
        return self.api.request(method, url, **kwargs)


@tagged('post_install', '-at_install')
class TestBackupGoogleDrive(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.admin_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_administrator')
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')

    def _gdrive_vals(self, **extra):
        vals = {
            'name': 'GDrive %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_folder': 'Odoo Backups',
            'google_drive_client_id': 'test-client.apps.googleusercontent.com',
            'google_drive_client_secret': 'test-client-secret',
            'google_drive_refresh_token': '1//test-refresh-token',
            'google_drive_access_token': 'ya29-test-access-token',
        }
        vals.update(extra)
        return vals

    def _create_authorized(self, **extra):
        return self.Storage.create(self._gdrive_vals(**extra))

    def _zip(self, temp_dir, name=None):
        if name is None:
            name = '%s_20260816_120000.zip' % self.env.cr.dbname
        workspace = Path(temp_dir) / 'workspace'
        workspace.mkdir()
        (workspace / DATABASE_DUMP_FILENAME).write_bytes(b'pg-dump-content')
        write_manifest_file(workspace / MANIFEST_FILENAME, {'database_name': self.env.cr.dbname})
        zip_path = Path(temp_dir) / name
        create_backup_zip(workspace, zip_path)
        return zip_path

    def _patch_api(self, api=None):
        api = api or FakeGoogleAPI()
        return patch(
            'odoo.addons.cb_auto_backup_manager.services.storage_providers.google_drive._require_requests',
            return_value=FakeRequests(api),
        ), api

    def test_configuration_validation(self):
        storage = self.Storage.create({
            'name': 'GDrive Empty %s' % uuid4().hex[:8],
            'type': 'google_drive',
        })
        provider = get_storage_provider(storage)
        with self.assertRaises(Exception):
            provider.validate()
        with self.assertRaises(ValidationError):
            storage.google_drive_folder = 'parent/child'

    def test_unauthorized_store_and_download_fail(self):
        storage = self.Storage.create({
            'name': 'GDrive No Token %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_client_id': 'client.apps.googleusercontent.com',
            'google_drive_client_secret': 'secret',
            'google_drive_folder': 'Odoo Backups',
        })
        provider = get_storage_provider(storage)
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / 'odoo19_20260816_120000.zip'
            zip_path.write_bytes(b'abc')
            stored = provider.store(str(zip_path), zip_path.name)
        self.assertFalse(stored.success)
        self.assertEqual(stored.status, 'failed')
        self.assertIn('not authorized', stored.error_message)
        downloaded = provider.download_backup('gdrive:not_a_valid', str(Path(tempfile.gettempdir()) / 'gdrive_out.zip'))
        self.assertFalse(downloaded.success)
        self.assertNotEqual(downloaded.status, 'not_implemented')

    def test_test_connection_success(self):
        storage = self._create_authorized()
        ctx, api = self._patch_api()
        with ctx:
            action = storage.action_test_connection()
        self.assertEqual(action['params']['type'], 'success')
        self.assertEqual(storage.validation_status, 'valid')
        self.assertEqual(storage.google_drive_connection_status, 'connected')
        self.assertEqual(storage.google_drive_account, 'backup@example.com')
        self.assertTrue(storage.google_drive_folder_id)

    def test_authentication_failure(self):
        storage = self._create_authorized()
        api = FakeGoogleAPI()
        api.fail_auth = True
        ctx, _api = self._patch_api(api)
        with ctx:
            action = storage.action_test_connection()
        self.assertEqual(action['params']['type'], 'danger')
        self.assertEqual(storage.validation_status, 'invalid')

    def test_timeout(self):
        storage = self._create_authorized()
        api = FakeGoogleAPI()
        api.fail_timeout = True
        ctx, _api = self._patch_api(api)
        with ctx:
            action = storage.action_test_connection()
        self.assertEqual(action['params']['type'], 'danger')
        self.assertIn('timed out', (action['params']['message'] or '').lower() + (storage.validation_message or '').lower())

    def test_quota_upload_failure(self):
        storage = self._create_authorized()
        api = FakeGoogleAPI()
        api.fail_quota = True
        ctx, _api = self._patch_api(api)
        with ctx, tempfile.TemporaryDirectory() as temp_dir:
            zip_path = self._zip(temp_dir)
            result = get_storage_provider(storage).store(
                str(zip_path), zip_path.name, relative_dir='%s/plan_1' % self.env.cr.dbname,
            )
        self.assertFalse(result.success)
        self.assertIn('quota', result.error_message.lower())

    def test_successful_upload_download_list_delete(self):
        storage = self._create_authorized()
        api = FakeGoogleAPI()
        ctx, _api = self._patch_api(api)
        with ctx, tempfile.TemporaryDirectory() as temp_dir:
            zip_path = self._zip(temp_dir)
            provider = get_storage_provider(storage)
            stored = provider.store(
                str(zip_path), zip_path.name, relative_dir='%s/plan_9' % self.env.cr.dbname,
            )
            self.assertTrue(stored.success)
            file_id = parse_google_drive_file_ref(stored.final_path)
            rec = api.files[file_id]
            rec['appProperties']['cb_database'] = self.env.cr.dbname
            rec['appProperties']['cb_plan_id'] = '9'
            listed = provider.list_backups(
                relative_dir='%s/plan_9' % self.env.cr.dbname,
                database_name=self.env.cr.dbname,
                plan_id=9,
            )
            self.assertTrue(listed.success)
            identified = [item for item in listed.files if item.identified]
            self.assertTrue(identified)
            local_copy = Path(temp_dir) / 'download.zip'
            downloaded = provider.download_backup(stored.final_path, str(local_copy))
            self.assertTrue(downloaded.success)
            self.assertEqual(local_copy.read_bytes(), zip_path.read_bytes())
            deleted = provider.delete_backup(stored.final_path)
            self.assertTrue(deleted.success)
            self.assertTrue(api.files[file_id].get('trashed'))

    def test_rejects_path_traversal_file_ref(self):
        with self.assertRaises(Exception):
            parse_google_drive_file_ref('../secrets.txt')
        with self.assertRaises(Exception):
            parse_google_drive_file_ref('/tmp/file.zip')

    def test_oauth_state_signature(self):
        storage = self._create_authorized()
        nonce = 'abc123'
        storage.sudo().write({'google_drive_oauth_nonce': nonce})
        body = '%s.%s.%s.%s' % (storage.id, self.env.uid, '9999999999', nonce)
        signature = self.Storage._sign_google_oauth_state(body)
        with self.assertRaises(UserError):
            self.Storage._parse_google_oauth_state('%s.%s' % (body, signature))
        with self.assertRaises(UserError):
            self.Storage._parse_google_oauth_state('1.2.3.4.notasignature')

    def test_connect_returns_google_url(self):
        storage = self._create_authorized()
        action = storage.action_connect_google_drive()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('accounts.google.com', action['url'])
        self.assertTrue(storage.google_drive_oauth_nonce)

    def test_operators_cannot_read_google_secrets(self):
        storage = self._create_authorized()
        operator = self.env['res.users'].create({
            'name': 'GDrive Operator %s' % uuid4().hex[:6],
            'login': 'gdrive_op_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [self.operator_group.id])],
        })
        with self.assertRaises(AccessError):
            storage.with_user(operator).google_drive_client_secret
        with self.assertRaises(AccessError):
            storage.with_user(operator).google_drive_refresh_token
        with self.assertRaises(UserError):
            storage.with_user(operator).action_connect_google_drive()

    def test_disconnect_clears_tokens(self):
        storage = self._create_authorized()
        storage.google_drive_connection_status = 'connected'
        action = storage.action_disconnect_google_drive()
        self.assertFalse(storage.google_drive_refresh_token)
        self.assertEqual(storage.google_drive_connection_status, 'disconnected')
        self.assertIn('disconnected', (action['params']['message'] or '').lower())

    def test_gdrive_only_plan_activates_when_connected(self):
        storage = self._create_authorized()
        ctx, _api = self._patch_api()
        with ctx:
            plan = self.env['cb.backup.plan'].create({
                'name': 'GDrive Plan %s' % uuid4().hex[:8],
                'database_name': self.env.cr.dbname,
                'timezone': 'UTC',
                'state': 'draft',
                'storage_destination_ids': [(6, 0, [storage.id])],
                'schedule_ids': [(0, 0, {
                    'frequency': 'daily',
                    'time_hour': 6,
                    'time_minute': 0,
                })],
            })
            plan.action_activate()
        self.assertEqual(plan.state, 'active')

    def test_tokens_never_appear_in_logs_message(self):
        storage = self._create_authorized()
        action = storage.action_connect_google_drive()
        self.assertNotIn('test-client-secret', action['url'])
        self.assertNotIn('1//test-refresh-token', action['url'])
