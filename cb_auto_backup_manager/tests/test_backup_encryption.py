# -*- coding: utf-8 -*-
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import odoo.release
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.cb_auto_backup_manager.models.backup_encryption import (
    DECRYPT_FAILED_MESSAGE,
    ENC_MAGIC,
    decrypt_backup_file,
    encrypt_backup_file,
    is_encrypted_backup_file,
    read_encrypted_header,
    validate_encrypted_container,
)
from odoo.addons.cb_auto_backup_manager.models.backup_encryption_profile import (
    ENCRYPTION_SECRET_MASK,
)
from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
    DATABASE_DUMP_FILENAME,
    FILESTORE_DIRNAME,
    MANIFEST_FILENAME,
    BackupError,
    build_backup_manifest,
    compute_sha256,
    create_backup_zip,
    identify_managed_backup,
    read_backup_manifest,
    write_manifest_file,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.factory import (
    get_storage_provider,
)
from odoo.addons.cb_auto_backup_manager.services.storage_providers.sftp import (
    SftpStorageProvider,
)
from odoo.addons.cb_auto_backup_manager.tests.test_backup_sftp import FakeSFTP, FakeSSH

TEST_SECRET = 'unit-test-secret-ok'
WRONG_SECRET = 'unit-test-wrong-xx'


@tagged('post_install', '-at_install')
class TestBackupEncryption(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env['cb.backup.storage']
        cls.Plan = cls.env['cb.backup.plan']
        cls.Profile = cls.env['cb.backup.encryption.profile']
        cls.History = cls.env['cb.backup.history']
        cls.Service = cls.env['cb.backup.service']
        cls.Restore = cls.env['cb.backup.restore.service']
        cls.operator_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_operator')
        cls.admin_group = cls.env.ref('cb_auto_backup_manager.group_cb_backup_administrator')

    def _operator(self):
        return self.env['res.users'].create({
            'name': 'Encryption Operator',
            'login': 'cb_enc_op_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.operator_group.id,
            ])],
        })

    def _admin_user(self):
        return self.env['res.users'].create({
            'name': 'Encryption Admin',
            'login': 'cb_enc_admin_%s' % uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.admin_group.id,
            ])],
        })

    def _create_profile(self, secret=TEST_SECRET, confirm=None):
        return self.Profile.create({
            'name': 'Profile %s' % uuid4().hex[:8],
            'method': 'aes256',
            'secret': secret,
            'secret_confirm': confirm if confirm is not None else secret,
        })

    def _create_local_storage(self, path):
        return self.Storage.create({
            'name': 'Enc Storage %s' % uuid4().hex[:8],
            'type': 'local',
            'local_path': path,
        })

    def _create_plan(self, storage, encryption_enabled=False, profile=None):
        vals = {
            'name': 'Enc Plan %s' % uuid4().hex[:8],
            'database_name': self.env.cr.dbname,
            'timezone': 'UTC',
            'state': 'draft',
            'storage_destination_ids': [(6, 0, [storage.id])],
            'schedule_ids': [(0, 0, {
                'frequency': 'daily',
                'time_hour': 6,
                'time_minute': 0,
            })],
            'encryption_enabled': encryption_enabled,
            'encryption_method': 'aes256' if encryption_enabled else 'none',
            'encryption_profile_id': profile.id if profile else False,
        }
        plan = self.Plan.create(vals)
        plan.action_activate()
        return plan

    def _ensure_filestore(self, database_name):
        filestore = Path(tempfile.mkdtemp()) / 'filestore' / database_name
        filestore.mkdir(parents=True, exist_ok=True)
        (filestore / 'attachment.bin').write_bytes(b'attachment')
        return filestore

    def _make_zip(self, directory, database_name=None):
        directory = Path(directory)
        workspace = directory / ('.ws_%s' % uuid4().hex[:6])
        workspace.mkdir()
        db_name = database_name or self.env.cr.dbname
        (workspace / DATABASE_DUMP_FILENAME).write_bytes(b'PGDMP\x00fake-dump')
        filestore = workspace / FILESTORE_DIRNAME
        filestore.mkdir()
        (filestore / 'attachment.bin').write_bytes(b'attachment')
        write_manifest_file(
            workspace / MANIFEST_FILENAME,
            build_backup_manifest(
                database_name=db_name,
                backup_datetime=datetime(2026, 8, 13, 23, 0, 0),
                odoo_version=odoo.release.version,
                module_version='19.0.9.0.0',
                filestore_included=True,
                encryption_method='aes256',
            ),
        )
        zip_path = directory / ('%s_20260813_230000.zip' % db_name)
        create_backup_zip(workspace, zip_path)
        return zip_path

    def test_encryption_disabled(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage, encryption_enabled=False)
            self.assertFalse(plan.encryption_enabled)
            self.assertEqual(plan.encryption_method, 'none')

    def test_encryption_enabled_and_profile_required(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            with self.assertRaises(ValidationError):
                self.Plan.create({
                    'name': 'Missing Profile %s' % uuid4().hex[:8],
                    'database_name': self.env.cr.dbname,
                    'timezone': 'UTC',
                    'storage_destination_ids': [(6, 0, [storage.id])],
                    'encryption_enabled': True,
                    'encryption_method': 'aes256',
                })

    def test_password_confirmation(self):
        with self.assertRaises(ValidationError):
            self._create_profile(secret=TEST_SECRET, confirm=WRONG_SECRET)
        profile = self._create_profile()
        self.assertTrue(profile.has_secret)

    def test_administrator_can_configure_profile(self):
        admin = self._admin_user()
        profile = self.Profile.with_user(admin).create({
            'name': 'Admin Profile %s' % uuid4().hex[:8],
            'secret': TEST_SECRET,
            'secret_confirm': TEST_SECRET,
        })
        self.assertTrue(profile.has_secret)
        self.assertEqual(profile.read(['secret'])[0]['secret'], ENCRYPTION_SECRET_MASK)

    def test_operator_cannot_retrieve_secret(self):
        profile = self._create_profile()
        operator = self._operator()
        with self.assertRaises(AccessError):
            self.Profile.with_user(operator).create({
                'name': 'Op Profile %s' % uuid4().hex[:8],
                'secret': TEST_SECRET,
                'secret_confirm': TEST_SECRET,
            })
        try:
            value = profile.with_user(operator).secret
            self.assertIn(value, (False, '', ENCRYPTION_SECRET_MASK, None))
        except AccessError:
            pass
        visible = profile.with_user(operator).read(['name', 'method'])
        self.assertTrue(visible)
        self.assertNotIn(TEST_SECRET, str(visible))

    def test_aes256_random_salt_nonce_and_decrypt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'plain.zip'
            source.write_bytes(b'plain-backup-bytes')
            first = Path(temp_dir) / 'one.enc'
            second = Path(temp_dir) / 'two.enc'
            encrypt_backup_file(source, first, TEST_SECRET, database_name='odoo19')
            encrypt_backup_file(source, second, TEST_SECRET, database_name='odoo19')
            header_a = read_encrypted_header(first)
            header_b = read_encrypted_header(second)
            self.assertNotEqual(header_a['salt'], header_b['salt'])
            self.assertNotEqual(header_a['nonce'], header_b['nonce'])
            self.assertEqual(header_a['encryption_algorithm'], 'AES-256-GCM')
            out = Path(temp_dir) / 'out.zip'
            decrypt_backup_file(first, out, TEST_SECRET)
            self.assertEqual(out.read_bytes(), b'plain-backup-bytes')

    def test_wrong_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'plain.zip'
            source.write_bytes(b'plain-backup-bytes')
            enc = Path(temp_dir) / 'backup.enc'
            encrypt_backup_file(source, enc, TEST_SECRET)
            with self.assertRaises(BackupError) as ctx:
                decrypt_backup_file(enc, Path(temp_dir) / 'out.zip', WRONG_SECRET)
            self.assertEqual(str(ctx.exception), DECRYPT_FAILED_MESSAGE)

    def test_corrupted_ciphertext_and_tag_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'plain.zip'
            source.write_bytes(b'plain-backup-bytes' * 50)
            enc = Path(temp_dir) / 'backup.enc'
            encrypt_backup_file(source, enc, TEST_SECRET, chunk_size=1024)
            data = bytearray(enc.read_bytes())
            data[-5] ^= 0xFF
            enc.write_bytes(bytes(data))
            with self.assertRaises(BackupError) as ctx:
                decrypt_backup_file(enc, Path(temp_dir) / 'out.zip', TEST_SECRET)
            self.assertEqual(str(ctx.exception), DECRYPT_FAILED_MESSAGE)

            truncated = Path(temp_dir) / 'truncated.enc'
            truncated.write_bytes(enc.read_bytes()[:40])
            with self.assertRaises(BackupError):
                validate_encrypted_container(truncated)

    def test_large_file_chunked_handling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'large.zip'
            payload = (b'ABCDEFGHIJ' * 400)
            source.write_bytes(payload)
            enc = Path(temp_dir) / 'large.enc'
            encrypt_backup_file(source, enc, TEST_SECRET, chunk_size=1024)
            out = Path(temp_dir) / 'out.zip'
            decrypt_backup_file(enc, out, TEST_SECRET)
            self.assertEqual(out.read_bytes(), payload)
            self.assertGreater(enc.stat().st_size, source.stat().st_size)

    def test_encrypted_backup_creation_and_plaintext_removed(self):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        filestore = self._ensure_filestore(self.env.cr.dbname)
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            profile = self._create_profile()
            plan = self._create_plan(storage, encryption_enabled=True, profile=profile)
            with patch.object(type(self.Service), '_run_pg_dump', side_effect=_fake_dump), patch.object(
                type(self.Service), 'get_filestore_path', return_value=filestore,
            ):
                self.Service.execute_plan_backup(plan, trigger='manual')
            history = self.History.search([('plan_id', '=', plan.id)], limit=1)
            self.assertEqual(history.status, 'success')
            self.assertTrue(history.encrypted)
            self.assertEqual(history.encryption_method, 'aes256')
            self.assertTrue(history.file_name.endswith('.enc'))
            stored = Path(history.file_path)
            self.assertTrue(stored.is_file())
            self.assertTrue(is_encrypted_backup_file(stored))
            self.assertEqual(history.checksum, compute_sha256(stored))
            self.assertFalse(list(Path(local_dir).rglob('*.zip')))
            identified, manifest, _reason = identify_managed_backup(
                stored, plan.database_name, plan_id=plan.id,
            )
            self.assertTrue(identified)
            self.assertTrue(manifest.get('encrypted'))

    def test_encrypted_backup_verification_and_restore(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_zip(local_dir)
            enc_path = Path(local_dir) / zip_path.name.replace('.zip', '.enc')
            encrypt_backup_file(
                zip_path, enc_path, TEST_SECRET,
                database_name=plan.database_name, plan_id=plan.id,
            )
            zip_path.unlink()
            history = self.History.create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'backup_datetime': fields.Datetime.now(),
                'file_name': enc_path.name,
                'file_path': str(enc_path),
                'file_size': enc_path.stat().st_size,
                'checksum': compute_sha256(enc_path),
                'status': 'success',
                'encrypted': True,
                'encryption_method': 'aes256',
                'destination_result_ids': [(0, 0, {
                    'storage_id': storage.id,
                    'storage_name': storage.name,
                    'storage_type': 'local',
                    'status': 'success',
                    'file_path': str(enc_path),
                    'file_size': enc_path.stat().st_size,
                })],
            })
            result = self.Restore.verify_backup(
                history, storage=storage, encryption_secret=TEST_SECRET,
            )
            self.assertTrue(result['success'])
            self.assertTrue(result['checksum_verified'])
            with patch.object(type(self.Restore), '_restore_dump'), patch.object(
                type(self.Restore), '_validate_temp_database',
            ):
                restore = self.Restore.test_restore(
                    history, storage=storage, cleanup_after_test=True,
                    encryption_secret=TEST_SECRET,
                )
            self.assertTrue(restore['success'])

    def test_checksum_mismatch_stops_before_decrypt(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_zip(local_dir)
            enc_path = Path(local_dir) / zip_path.name.replace('.zip', '.enc')
            encrypt_backup_file(zip_path, enc_path, TEST_SECRET, database_name=plan.database_name)
            history = self.History.create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'file_name': enc_path.name,
                'file_path': str(enc_path),
                'checksum': '0' * 64,
                'status': 'success',
                'encrypted': True,
                'encryption_method': 'aes256',
                'destination_result_ids': [(0, 0, {
                    'storage_id': storage.id,
                    'storage_name': storage.name,
                    'storage_type': 'local',
                    'status': 'success',
                    'file_path': str(enc_path),
                })],
            })
            result = self.Restore.verify_backup(
                history, storage=storage, encryption_secret=TEST_SECRET,
            )
            self.assertFalse(result['success'])
            self.assertIn('integrity', result['error_message'].lower())

    def test_secrets_not_in_manifest_logs_or_notifications(self):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        filestore = self._ensure_filestore(self.env.cr.dbname)
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            profile = self._create_profile()
            plan = self._create_plan(storage, encryption_enabled=True, profile=profile)
            logged = []
            handler = logging.Handler()
            handler.emit = lambda record: logged.append(record.getMessage())
            logger = logging.getLogger('odoo.addons.cb_auto_backup_manager')
            logger.addHandler(handler)
            try:
                with patch.object(type(self.Service), '_run_pg_dump', side_effect=_fake_dump), patch.object(
                    type(self.Service), 'get_filestore_path', return_value=filestore,
                ):
                    action = plan.action_backup_now()
            finally:
                logger.removeHandler(handler)
            history = self.History.search([('plan_id', '=', plan.id)], limit=1)
            with tempfile.TemporaryDirectory() as unzip_dir:
                decrypt_backup_file(history.file_path, Path(unzip_dir) / 'b.zip', TEST_SECRET)
                manifest = read_backup_manifest(Path(unzip_dir) / 'b.zip')
            self.assertNotIn(TEST_SECRET, str(manifest))
            self.assertNotIn('password', manifest)
            self.assertNotIn(TEST_SECRET, '\n'.join(logged))
            self.assertNotIn(TEST_SECRET, action['params']['message'])
            self.assertIn('Encrypted backup completed successfully.', action['params']['message'])

    def test_cleanup_after_encryption_failure(self):
        def _fake_dump(db_name, dump_path):
            Path(dump_path).write_bytes(b'fake-dump')

        filestore = self._ensure_filestore(self.env.cr.dbname)
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            profile = self._create_profile()
            plan = self._create_plan(storage, encryption_enabled=True, profile=profile)
            with patch.object(type(self.Service), '_run_pg_dump', side_effect=_fake_dump), patch.object(
                type(self.Service), 'get_filestore_path', return_value=filestore,
            ), patch(
                'odoo.addons.cb_auto_backup_manager.models.backup_service.encrypt_backup_file',
                side_effect=BackupError('Backup encryption failed.'),
            ):
                result = self.Service.execute_plan_backup(plan, trigger='scheduled')
            self.assertFalse(result)
            self.assertFalse(list(Path(local_dir).rglob('*.zip')))
            self.assertFalse(list(Path(local_dir).rglob('*.enc')))
            history = self.History.search([('plan_id', '=', plan.id)], limit=1)
            self.assertEqual(history.status, 'failed')
            self.assertIn('encryption failed', (history.error_message or '').lower())

    def test_sftp_download_encrypted_artifact(self):
        with tempfile.TemporaryDirectory() as sandbox:
            remote_root = Path(sandbox) / 'backups' / 'odoo'
            remote_root.mkdir(parents=True)
            zip_path = self._make_zip(sandbox)
            enc_path = remote_root / zip_path.name.replace('.zip', '.enc')
            encrypt_backup_file(zip_path, enc_path, TEST_SECRET, database_name=self.env.cr.dbname)
            storage = self.Storage.create({
                'name': 'Enc SFTP %s' % uuid4().hex[:8],
                'type': 'sftp',
                'sftp_host': 'sftp.example.com',
                'sftp_port': 22,
                'sftp_username': 'backup',
                'sftp_authentication_type': 'password',
                'sftp_password': 'not-the-backup-secret',
                'sftp_remote_path': '/backups/odoo',
                'sftp_host_key': 'SHA256:testhostkey',
            })
            fake = FakeSFTP(sandbox)
            ssh = FakeSSH()
            local_copy = Path(sandbox) / 'downloaded.enc'
            with patch.object(SftpStorageProvider, '_require_paramiko', return_value=None), patch.object(
                SftpStorageProvider, '_open_session', return_value=(ssh, fake),
            ):
                result = get_storage_provider(storage).download_backup(
                    '/backups/odoo/%s' % enc_path.name, str(local_copy),
                )
            self.assertTrue(result.success)
            self.assertTrue(is_encrypted_backup_file(local_copy))
            self.assertEqual(local_copy.read_bytes()[:8], ENC_MAGIC)

    def test_google_drive_encrypted_store_requires_authorization(self):
        storage = self.Storage.create({
            'name': 'Enc GDrive %s' % uuid4().hex[:8],
            'type': 'google_drive',
            'google_drive_account': 'backup@example.com',
        })
        with tempfile.NamedTemporaryFile(suffix='.enc') as handle:
            result = get_storage_provider(storage).store(handle.name, 'odoo19_20260813_230000.enc')
        self.assertEqual(result.status, 'failed')

    def test_notification_decrypt_failure_hides_secret(self):
        with tempfile.TemporaryDirectory() as local_dir:
            storage = self._create_local_storage(local_dir)
            plan = self._create_plan(storage)
            zip_path = self._make_zip(local_dir)
            enc_path = Path(local_dir) / zip_path.name.replace('.zip', '.enc')
            encrypt_backup_file(zip_path, enc_path, TEST_SECRET, database_name=plan.database_name)
            history = self.History.create({
                'plan_id': plan.id,
                'database_name': plan.database_name,
                'file_name': enc_path.name,
                'file_path': str(enc_path),
                'checksum': compute_sha256(enc_path),
                'status': 'success',
                'encrypted': True,
                'encryption_method': 'aes256',
                'destination_result_ids': [(0, 0, {
                    'storage_id': storage.id,
                    'storage_name': storage.name,
                    'storage_type': 'local',
                    'status': 'success',
                    'file_path': str(enc_path),
                })],
            })
            wizard = self.env['cb.backup.restore.wizard'].with_context(
                default_history_id=history.id,
                default_restore_mode='verify_only',
            ).create({
                'history_id': history.id,
                'encryption_secret': WRONG_SECRET,
            })
            action = wizard.action_verify()
            self.assertEqual(action['params']['type'], 'danger')
            self.assertIn('could not be decrypted', action['params']['message'].lower())
            self.assertNotIn(WRONG_SECRET, action['params']['message'])
            self.assertFalse(wizard.encryption_secret)

    def test_dashboard_encryption_coverage_and_cron(self):
        dash = self.env['cb.backup.dashboard'].create({})
        self.assertTrue(dash.kpi_encrypted_coverage)
        crons = self.env['ir.cron'].search([('model_id.model', '=', 'cb.backup.plan')])
        self.assertEqual(len(crons), 1)
