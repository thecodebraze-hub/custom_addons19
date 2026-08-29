# -*- coding: utf-8 -*-
import errno
import posixpath
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    MANIFEST_FILENAME,
    BackupError,
    build_backup_manifest,
    create_backup_zip,
    generate_backup_filename,
    is_sftp_path_inside,
    join_sftp_path,
    normalize_sftp_root,
    write_manifest_file,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.base import StorageResult
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.local import (
    LocalStorageProvider,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.sftp import (
    FingerprintHostKeyPolicy,
    SftpStorageProvider,
    format_ssh_key_fingerprint,
)


class FakeSSH:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeAttr:
    def __init__(self, path):
        st = path.stat()
        self.filename = path.name
        self.st_size = st.st_size
        self.st_mode = st.st_mode
        self.st_mtime = st.st_mtime


class FakeSFTP:
    """Filesystem-backed SFTP stand-in for tests. No network, no Paramiko."""

    def __init__(self, sandbox):
        self.sandbox = Path(sandbox)
        self.closed = False
        self.fail_write = False
        self.fail_rename = False
        self.fail_auth = False

    def close(self):
        self.closed = True

    def _map(self, remote):
        remote_n = posixpath.normpath((remote or '').replace('\\', '/'))
        rel = remote_n.lstrip('/')
        mapped = (self.sandbox / rel).resolve()
        if self.sandbox.resolve() not in mapped.parents and mapped != self.sandbox.resolve():
            raise PermissionError('path traversal')
        return mapped

    def stat(self, remote):
        path = self._map(remote)
        if not path.exists():
            raise FileNotFoundError(errno.ENOENT, 'No such file', remote)
        return FakeAttr(path)

    def listdir_attr(self, remote):
        path = self._map(remote)
        return [FakeAttr(child) for child in path.iterdir()]

    def mkdir(self, remote):
        self._map(remote).mkdir()

    def open(self, remote, mode='r'):
        path = self._map(remote)
        if self.fail_write and 'w' in mode:
            raise OSError(errno.EIO, 'write failed')
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open(mode)

    def remove(self, remote):
        path = self._map(remote)
        if not path.exists():
            raise FileNotFoundError(errno.ENOENT, 'No such file', remote)
        path.unlink()

    def posix_rename(self, old, new):
        if self.fail_rename:
            raise OSError(errno.EIO, 'rename failed')
        src = self._map(old)
        dest = self._map(new)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dest)

    def rename(self, old, new):
        self.posix_rename(old, new)


@tagged('post_install', '-at_install')
class TestBackupSftp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.Service = cls.env['cb.backup.service']
        cls.Cleanup = cls.env['cb.backup.cleanup.service']
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')

    def _sftp_vals(self, **kwargs):
        vals = {
            'name': 'SFTP Storage %s' % uuid4().hex[:8],
            'type': 'sftp',
            'sftp_host': 'backup.example.com',
            'sftp_port': 22,
            'sftp_username': 'backupuser',
            'sftp_authentication_type': 'password',
            'sftp_password': 'secret-password',
            'sftp_remote_path': '/backups/odoo',
            'sftp_host_key': 'SHA256:configuredfingerprint',
        }
        vals.update(kwargs)
        return vals

    def _create_sftp_storage(self, **kwargs):
        return self.Storage.create(self._sftp_vals(**kwargs))

    @contextmanager
    def _patched_sftp(self, sandbox):
        fake = FakeSFTP(sandbox)
        ssh = FakeSSH()
        (Path(sandbox) / 'backups' / 'odoo').mkdir(parents=True, exist_ok=True)
        with patch.object(SftpStorageProvider, '_require_paramiko', return_value=None), patch.object(
            SftpStorageProvider,
            '_open_session',
            return_value=(ssh, fake),
        ):
            yield fake, ssh

    def _write_managed_zip(self, directory, database_name, plan_id, backup_dt):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        workspace = directory / ('.ws_%s' % uuid4().hex[:6])
        workspace.mkdir()
        (workspace / DATABASE_DUMP_FILENAME).write_bytes(b'dump')
        write_manifest_file(
            workspace / MANIFEST_FILENAME,
            build_backup_manifest(
                database_name=database_name,
                backup_datetime=backup_dt,
                odoo_version='19.0',
                module_version='19.0.5.0.0',
                filestore_included=True,
                plan_id=plan_id,
                plan_identifier='plan_%s' % plan_id,
            ),
        )
        filename = generate_backup_filename(database_name, backup_dt)
        zip_path = directory / filename
        create_backup_zip(workspace, zip_path)
        return zip_path

    def _ensure_filestore(self, database_name):
        filestore = Path(tempfile.mkdtemp()) / 'filestore' / database_name
        filestore.mkdir(parents=True, exist_ok=True)
        (filestore / 'attachment.bin').write_bytes(b'attachment')
        return filestore

    def test_sftp_configuration_validation(self):
        storage = self._create_sftp_storage()
        provider = get_storage_provider(storage)
        provider.validate(connect=False)
        self.assertEqual(normalize_sftp_root(storage.sftp_remote_path), '/backups/odoo')

    def test_invalid_host(self):
        with self.assertRaises(BackupError):
            get_storage_provider(self._create_sftp_storage(sftp_host='bad host')).validate(connect=False)
        with self.assertRaises(ValidationError):
            self._create_sftp_storage(sftp_host='')

    def test_invalid_port(self):
        with self.assertRaises(ValidationError):
            self._create_sftp_storage(sftp_port=0)
        with self.assertRaises(ValidationError):
            self._create_sftp_storage(sftp_port=70000)

    def test_missing_username(self):
        with self.assertRaises(ValidationError):
            self._create_sftp_storage(sftp_username='')

    def test_password_authentication_configuration(self):
        storage = self._create_sftp_storage(
            sftp_authentication_type='password',
            sftp_password='secret-password',
        )
        get_storage_provider(storage).validate(connect=False)
        storage.sftp_password = False
        with self.assertRaises(BackupError):
            get_storage_provider(storage).validate(connect=False)

    def test_private_key_configuration(self):
        storage = self._create_sftp_storage(
            sftp_authentication_type='private_key',
            sftp_password=False,
            sftp_private_key='-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----',
            sftp_private_key_passphrase='optional-pass',
        )
        get_storage_provider(storage).validate(connect=False)
        storage.sftp_private_key = False
        with self.assertRaises(BackupError):
            get_storage_provider(storage).validate(connect=False)

    def test_invalid_remote_path(self):
        with self.assertRaises(ValidationError):
            self._create_sftp_storage(sftp_remote_path='relative/path')
        with self.assertRaises(ValidationError):
            self._create_sftp_storage(sftp_remote_path='/backups/../etc')

    def test_path_traversal_rejection(self):
        self.assertFalse(is_sftp_path_inside('/backups/odoo', '/backups/odoo/../../etc/passwd'))
        self.assertFalse(is_sftp_path_inside('/backups/odoo', '/etc/passwd'))
        self.assertTrue(is_sftp_path_inside('/backups/odoo', '/backups/odoo/db/plan_1/file.zip'))
        with self.assertRaises(BackupError):
            join_sftp_path('/backups/odoo', '../etc')

    def test_test_connection_success(self):
        storage = self._create_sftp_storage()
        with tempfile.TemporaryDirectory() as sandbox:
            with self._patched_sftp(sandbox):
                action = storage.action_test_connection()
        self.assertEqual(storage.validation_status, 'valid')
        self.assertEqual(action['params']['message'], 'Storage connection successful.')

    def test_authentication_failure(self):
        storage = self._create_sftp_storage()
        provider = get_storage_provider(storage)
        with patch.object(SftpStorageProvider, '_require_paramiko', return_value=None), patch.object(
            SftpStorageProvider,
            '_open_session',
            side_effect=BackupError('SFTP authentication failed.'),
        ):
            with self.assertRaises(BackupError) as ctx:
                provider.test_connection()
        self.assertEqual(str(ctx.exception), 'SFTP authentication failed.')
        self.assertNotIn('secret-password', str(ctx.exception))

    def test_host_key_mismatch(self):
        storage = self._create_sftp_storage(sftp_host_key='SHA256:expected')
        provider = get_storage_provider(storage)
        with patch.object(SftpStorageProvider, '_require_paramiko', return_value=None), patch.object(
            SftpStorageProvider,
            '_open_session',
            side_effect=BackupError('SFTP host key does not match the configured fingerprint.'),
        ):
            with self.assertRaises(BackupError) as ctx:
                provider.test_connection()
        self.assertIn('host key', str(ctx.exception).lower())

    def test_fingerprint_host_key_policy(self):
        class FakeKey:
            def asbytes(self):
                return b'example-host-key'

            def get_name(self):
                return 'ssh-ed25519'

        class FakeHostKeys:
            def __init__(self):
                self.added = []

            def add(self, hostname, keytype, key):
                self.added.append((hostname, keytype, key))

        class FakeClient:
            def __init__(self):
                self._keys = FakeHostKeys()

            def get_host_keys(self):
                return self._keys

        key = FakeKey()
        expected = format_ssh_key_fingerprint(key)
        client = FakeClient()
        FingerprintHostKeyPolicy(expected).missing_host_key(client, 'backup.example.com', key)
        self.assertEqual(client.get_host_keys().added[0][0], 'backup.example.com')

        with self.assertRaises(BackupError) as missing:
            FingerprintHostKeyPolicy('').missing_host_key(FakeClient(), 'backup.example.com', key)
        self.assertIn('not configured', str(missing.exception))
        self.assertIn(expected, str(missing.exception))

        with self.assertRaises(BackupError) as mismatch:
            FingerprintHostKeyPolicy('SHA256:otherfingerprint').missing_host_key(
                FakeClient(), 'backup.example.com', key,
            )
        self.assertIn('does not match', str(mismatch.exception))

    def test_successful_upload_and_verification(self):
        storage = self._create_sftp_storage()
        with tempfile.TemporaryDirectory() as sandbox, tempfile.TemporaryDirectory() as source_dir:
            zip_path = self._write_managed_zip(
                source_dir, 'testdb', 1, datetime(2026, 8, 13, 23, 0, 0),
            )
            with self._patched_sftp(sandbox) as (fake, ssh):
                result = get_storage_provider(storage).store(
                    str(zip_path), zip_path.name, relative_dir='testdb/plan_1',
                )
            self.assertTrue(result.success)
            self.assertEqual(result.file_size, zip_path.stat().st_size)
            remote = Path(sandbox) / 'backups' / 'odoo' / 'testdb' / 'plan_1' / zip_path.name
            self.assertTrue(remote.is_file())
            self.assertFalse(list(remote.parent.glob('*.uploading')))
            self.assertTrue(ssh.closed or fake.closed)

    def test_failed_upload(self):
        storage = self._create_sftp_storage()
        with tempfile.TemporaryDirectory() as sandbox, tempfile.TemporaryDirectory() as source_dir:
            zip_path = self._write_managed_zip(
                source_dir, 'testdb', 1, datetime(2026, 8, 13, 23, 0, 0),
            )
            with self._patched_sftp(sandbox) as (fake, _ssh):
                fake.fail_write = True
                result = get_storage_provider(storage).store(
                    str(zip_path), zip_path.name, relative_dir='testdb/plan_1',
                )
            self.assertFalse(result.success)
            self.assertEqual(result.status, 'failed')

    def test_partial_upload_cleanup(self):
        storage = self._create_sftp_storage()
        with tempfile.TemporaryDirectory() as sandbox, tempfile.TemporaryDirectory() as source_dir:
            zip_path = self._write_managed_zip(
                source_dir, 'testdb', 1, datetime(2026, 8, 13, 23, 0, 0),
            )
            with self._patched_sftp(sandbox) as (fake, _ssh):
                fake.fail_rename = True
                result = get_storage_provider(storage).store(
                    str(zip_path), zip_path.name, relative_dir='testdb/plan_1',
                )
            self.assertFalse(result.success)
            dest = Path(sandbox) / 'backups' / 'odoo' / 'testdb' / 'plan_1'
            self.assertFalse(list(dest.glob('*.zip')))
            self.assertFalse(list(dest.glob('*.uploading')))

    def test_remote_file_verification_and_deletion(self):
        storage = self._create_sftp_storage()
        with tempfile.TemporaryDirectory() as sandbox, tempfile.TemporaryDirectory() as source_dir:
            zip_path = self._write_managed_zip(
                source_dir, 'testdb', 7, datetime(2026, 7, 1, 6, 0, 0),
            )
            with self._patched_sftp(sandbox):
                provider = get_storage_provider(storage)
                stored = provider.store(str(zip_path), zip_path.name, relative_dir='testdb/plan_7')
                self.assertTrue(stored.success)
                listed = provider.list_backups(
                    relative_dir='testdb/plan_7',
                    database_name='testdb',
                    plan_id=7,
                )
                self.assertTrue(listed.success)
                self.assertEqual(len(listed.files), 1)
                self.assertTrue(listed.files[0].identified)
                deleted = provider.delete_backup(stored.final_path)
                self.assertTrue(deleted.success)
                self.assertFalse((Path(sandbox) / 'backups' / 'odoo' / 'testdb' / 'plan_7' / zip_path.name).exists())

    def test_retention_cleanup_through_sftp_provider(self):
        storage = self._create_sftp_storage()
        with tempfile.TemporaryDirectory() as sandbox, tempfile.TemporaryDirectory() as local_dir:
            local = self.Storage.create({
                'name': 'Local With SFTP %s' % uuid4().hex[:8],
                'type': 'local',
                'local_path': local_dir,
            })
            plan = self.Plan.create({
                'name': 'SFTP Cleanup Plan %s' % uuid4().hex[:8],
                'database_name': self.env.cr.dbname,
                'timezone': 'UTC',
                'state': 'draft',
                'retention_days': 30,
                'storage_destination_ids': [(6, 0, [storage.id, local.id])],
                'schedule_ids': [(0, 0, {'frequency': 'daily', 'time_hour': 6, 'time_minute': 0})],
            })
            relative = plan.get_storage_relative_dir()
            old_dt = datetime(2026, 7, 1, 6, 0, 0)
            recent_dt = datetime(2026, 8, 10, 6, 0, 0)
            with self._patched_sftp(sandbox):
                with patch.object(type(plan), '_validate_for_activation', return_value=True):
                    plan.action_activate()
                dest = Path(sandbox) / 'backups' / 'odoo' / Path(relative)
                old_zip = self._write_managed_zip(dest, plan.database_name, plan.id, old_dt)
                recent_zip = self._write_managed_zip(dest, plan.database_name, plan.id, recent_dt)
                notes = dest / 'notes.txt'
                notes.write_text('keep me')
                with patch(
                    'odoo.addons.cb_auto_backup_manager.models.backup_cleanup_service.fields.Datetime.now',
                    return_value=datetime(2026, 8, 12, 23, 0, 0),
                ):
                    logs = self.Cleanup.cleanup_plan(plan, trigger='manual')
                sftp_logs = logs.filtered(lambda log: log.storage_id == storage)
                self.assertTrue(sftp_logs)
                self.assertFalse(old_zip.exists())
                self.assertTrue(recent_zip.exists())
                self.assertTrue(notes.exists())

    def test_multiple_destination_backup_and_mixed_results(self):
        with tempfile.TemporaryDirectory() as local_dir, tempfile.TemporaryDirectory() as sandbox:
            local = self.Storage.create({
                'name': 'Local Mixed %s' % uuid4().hex[:8],
                'type': 'local',
                'local_path': local_dir,
            })
            sftp = self._create_sftp_storage()
            plan = self.Plan.create({
                'name': 'Mixed Dest Plan %s' % uuid4().hex[:8],
                'database_name': self.env.cr.dbname,
                'timezone': 'UTC',
                'state': 'active',
                'storage_destination_ids': [(6, 0, [local.id, sftp.id])],
                'schedule_ids': [(0, 0, {'frequency': 'daily', 'time_hour': 1, 'time_minute': 0})],
            })
            filestore = self._ensure_filestore(self.env.cr.dbname)

            def _fake_dump(db_name, dump_path):
                Path(dump_path).write_bytes(b'fake-dump')

            with self._patched_sftp(sandbox), patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump',
                side_effect=_fake_dump,
            ), patch.object(
                type(self.Service), 'get_filestore_path', return_value=filestore,
            ):
                self.Service.execute_plan_backup(plan, trigger='manual')

            history = self.env['cb.backup.history'].search([('plan_id', '=', plan.id)], limit=1)
            statuses = set(history.destination_result_ids.mapped('status'))
            self.assertIn('success', statuses)
            self.assertTrue(history.destination_summary)

            fail_result = StorageResult(
                success=False,
                destination=sftp.name,
                status='failed',
                error_message='SFTP authentication failed.',
                metadata={'storage_id': sftp.id},
            )
            with patch.object(SftpStorageProvider, 'store', return_value=fail_result), patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump',
                side_effect=_fake_dump,
            ), patch.object(
                type(self.Service), 'get_filestore_path', return_value=filestore,
            ):
                self.Service.execute_plan_backup(plan, trigger='manual')
            failed_history = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ], order='id desc', limit=1)
            dest_by_type = {
                line.storage_type: line.status
                for line in failed_history.destination_result_ids
            }
            self.assertEqual(dest_by_type.get('local'), 'success')
            self.assertEqual(dest_by_type.get('sftp'), 'failed')
            self.assertEqual(failed_history.status, 'partial')

            local_fail = StorageResult(
                success=False,
                destination=local.name,
                status='failed',
                error_message='Local storage failed.',
                metadata={'storage_id': local.id},
            )
            sftp_ok = StorageResult(
                success=True,
                destination=sftp.name,
                status='success',
                final_path='/backups/odoo/file.zip',
                file_size=10,
                metadata={'storage_id': sftp.id},
            )
            with patch.object(LocalStorageProvider, 'store', return_value=local_fail), patch.object(
                SftpStorageProvider, 'store', return_value=sftp_ok,
            ), patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_service.CbBackupService._run_pg_dump',
                side_effect=_fake_dump,
            ), patch.object(
                type(self.Service), 'get_filestore_path', return_value=filestore,
            ):
                self.Service.execute_plan_backup(plan, trigger='manual')
            mixed = self.env['cb.backup.history'].search([
                ('plan_id', '=', plan.id),
            ], order='id desc', limit=1)
            dest_by_type = {
                line.storage_type: line.status
                for line in mixed.destination_result_ids
            }
            self.assertEqual(dest_by_type.get('local'), 'failed')
            self.assertEqual(dest_by_type.get('sftp'), 'success')

    def test_credentials_never_appear_in_logs(self):
        storage = self._create_sftp_storage(sftp_password='secret-password')
        with tempfile.TemporaryDirectory() as sandbox, tempfile.TemporaryDirectory() as source_dir:
            zip_path = self._write_managed_zip(
                source_dir, 'testdb', 1, datetime(2026, 8, 13, 23, 0, 0),
            )
            with self._patched_sftp(sandbox), patch(
                'odoo.addons.cb_auto_backup_manager.services.storage_providers.sftp._logger'
            ) as mock_log:
                get_storage_provider(storage).store(
                    str(zip_path), zip_path.name, relative_dir='testdb/plan_1',
                )
                logged = ' '.join(str(call) for call in mock_log.mock_calls)
            self.assertNotIn('secret-password', logged)

    def test_operators_cannot_read_sftp_secrets(self):
        storage = self._create_sftp_storage()
        operator = self.env['res.users'].create({
            'name': 'SFTP Operator',
            'login': 'cb_sftp_op_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.operator_group.id,
            ])],
        })
        with self.assertRaises(AccessError):
            storage.with_user(operator).sftp_password
        with self.assertRaises(UserError):
            storage.with_user(operator).action_test_connection()

    def test_sftp_only_plan_can_activate_when_valid(self):
        storage = self._create_sftp_storage()
        plan = self.Plan.create({
            'name': 'SFTP Only Plan %s' % uuid4().hex[:8],
            'database_name': self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'storage_destination_ids': [(6, 0, [storage.id])],
            'schedule_ids': [(0, 0, {'frequency': 'daily', 'time_hour': 6, 'time_minute': 0})],
        })
        with tempfile.TemporaryDirectory() as sandbox:
            with self._patched_sftp(sandbox):
                plan.action_activate()
        self.assertEqual(plan.state, 'active')
        self.assertEqual(storage.validation_status, 'valid')
