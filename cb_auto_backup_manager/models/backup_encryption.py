# -*- coding: utf-8 -*-
"""
Encrypted backup container format (CBBKENC1).

Layout:
    magic (8 bytes) = b'CBBKENC1'
    header_length (uint32 little-endian)
    header JSON (UTF-8)
    chunked AES-256-GCM ciphertext (each chunk is ciphertext || 16-byte tag)

The password and derived key are never stored. Salt and nonce are public.
Chunked AES-256-GCM avoids loading multi-GB backups into memory.

Odoo 19 pins cryptography 42.0.8, which does not ship Argon2id. Password-based
keys are derived with scrypt (memory-hard KDF from the same library).
"""
import json
import logging
import os
import stat
import struct
from pathlib import Path

from .backup_utils import BackupError, sanitize_error_message

_logger = logging.getLogger(__name__)

ENC_MAGIC = b'CBBKENC1'
ENC_FORMAT_VERSION = 1
ENC_ALGORITHM = 'AES-256-GCM'
ENC_KDF = 'scrypt'
ENC_EXTENSION = '.enc'
CHUNK_SIZE = 1024 * 1024
SALT_SIZE = 16
NONCE_RANDOM_SIZE = 8
GCM_NONCE_SIZE = 12
GCM_TAG_SIZE = 16
KEY_SIZE = 32
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
MIN_PASSWORD_LENGTH = 12
HEADER_LEN_STRUCT = struct.Struct('<I')
CHUNK_INDEX_STRUCT = struct.Struct('>I')

DECRYPT_FAILED_MESSAGE = 'Unable to decrypt backup. Check the encryption secret.'
CORRUPT_CONTAINER_MESSAGE = 'Encrypted backup is corrupted or was modified.'
ENCRYPTION_FAILED_MESSAGE = 'Backup encryption failed.'


def restrict_file_permissions(path):
    """Best-effort owner-only permissions. Not available on all platforms."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def unlink_quietly(path):
    """Remove a file without claiming forensic-grade deletion."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        _logger.warning('Unable to remove temporary backup file.')


def is_encrypted_backup_file(path):
    """Return True when the file starts with the encrypted container magic."""
    try:
        with Path(path).open('rb') as handle:
            return handle.read(len(ENC_MAGIC)) == ENC_MAGIC
    except OSError:
        return False


def is_encrypted_backup_fileobj(fileobj):
    position = fileobj.tell()
    try:
        fileobj.seek(0)
        return fileobj.read(len(ENC_MAGIC)) == ENC_MAGIC
    except OSError:
        return False
    finally:
        try:
            fileobj.seek(position)
        except OSError:
            pass


def _require_crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:
        raise BackupError(
            'Backup encryption is unavailable because the cryptography library '
            'is not installed on this server.'
        ) from exc
    return AESGCM, Scrypt


def _normalize_password(password):
    if password is None:
        raise BackupError(DECRYPT_FAILED_MESSAGE)
    if isinstance(password, bytes):
        secret = password
    else:
        secret = str(password).encode('utf-8')
    if not secret or secret == b'********':
        raise BackupError(DECRYPT_FAILED_MESSAGE)
    return secret


def _derive_key(password_bytes, salt, n, r, p):
    _AESGCM, Scrypt = _require_crypto()
    kdf = Scrypt(salt=salt, length=KEY_SIZE, n=n, r=r, p=p)
    try:
        return kdf.derive(password_bytes)
    except Exception as exc:
        raise BackupError(ENCRYPTION_FAILED_MESSAGE) from exc


def _chunk_nonce(base_nonce, index):
    if index < 0 or index > 0xFFFFFFFF:
        raise BackupError(ENCRYPTION_FAILED_MESSAGE)
    return base_nonce[:NONCE_RANDOM_SIZE] + CHUNK_INDEX_STRUCT.pack(index)


def _chunk_aad(header_bytes, index):
    return header_bytes + CHUNK_INDEX_STRUCT.pack(index)


def _build_header(salt, nonce, chunk_size, database_name=None, plan_id=None, backup_datetime=None):
    header = {
        'format_version': ENC_FORMAT_VERSION,
        'encryption_algorithm': ENC_ALGORITHM,
        'kdf_algorithm': ENC_KDF,
        'kdf_n': SCRYPT_N,
        'kdf_r': SCRYPT_R,
        'kdf_p': SCRYPT_P,
        'salt': salt.hex(),
        'nonce': nonce.hex(),
        'chunk_size': int(chunk_size),
    }
    if database_name:
        header['database_name'] = database_name
    if plan_id:
        header['plan_id'] = int(plan_id)
    if backup_datetime:
        header['backup_datetime'] = backup_datetime
    return header


def _encode_header(header):
    payload = json.dumps(header, separators=(',', ':'), sort_keys=True).encode('utf-8')
    return HEADER_LEN_STRUCT.pack(len(payload)) + payload, payload


def read_encrypted_header_from_fileobj(fileobj):
    """Parse and return the public header dict. Does not decrypt."""
    fileobj.seek(0)
    magic = fileobj.read(len(ENC_MAGIC))
    if magic != ENC_MAGIC:
        raise BackupError('Backup file is not a valid encrypted backup.')
    length_raw = fileobj.read(HEADER_LEN_STRUCT.size)
    if len(length_raw) != HEADER_LEN_STRUCT.size:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE)
    header_len = HEADER_LEN_STRUCT.unpack(length_raw)[0]
    if header_len < 2 or header_len > 64 * 1024:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE)
    raw = fileobj.read(header_len)
    if len(raw) != header_len:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE)
    try:
        header = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE) from exc
    if not isinstance(header, dict):
        raise BackupError(CORRUPT_CONTAINER_MESSAGE)
    header['_header_bytes'] = raw
    header['_header_end'] = fileobj.tell()
    return header


def read_encrypted_header(path):
    with Path(path).open('rb') as handle:
        return read_encrypted_header_from_fileobj(handle)


def validate_encrypted_container(path):
    """Validate encrypted container structure without decrypting."""
    file_path = Path(path)
    if not file_path.exists():
        raise BackupError('Backup file does not exist.')
    if not file_path.is_file():
        raise BackupError('Backup path is not a readable file.')
    try:
        with file_path.open('rb') as handle:
            handle.read(1)
    except OSError as exc:
        raise BackupError('Backup file is not readable.') from exc

    header = read_encrypted_header(file_path)
    if int(header.get('format_version') or 0) != ENC_FORMAT_VERSION:
        raise BackupError('Unsupported encrypted backup format.')
    if header.get('encryption_algorithm') != ENC_ALGORITHM:
        raise BackupError('Unsupported backup encryption algorithm.')
    if header.get('kdf_algorithm') != ENC_KDF:
        raise BackupError('Unsupported backup key derivation algorithm.')
    try:
        salt = bytes.fromhex(header.get('salt') or '')
        nonce = bytes.fromhex(header.get('nonce') or '')
        chunk_size = int(header.get('chunk_size') or 0)
    except (TypeError, ValueError) as exc:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE) from exc
    if len(salt) != SALT_SIZE or len(nonce) != GCM_NONCE_SIZE:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE)
    if chunk_size < 1024 or chunk_size > 16 * 1024 * 1024:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE)
    ciphertext_size = file_path.stat().st_size - int(header.get('_header_end') or 0)
    if ciphertext_size <= GCM_TAG_SIZE:
        raise BackupError('Encrypted backup ciphertext is empty.')
    return header


def encrypt_backup_file(source_path, dest_path, password, database_name=None,
                        plan_id=None, backup_datetime=None, chunk_size=CHUNK_SIZE):
    """Encrypt source_path to dest_path using AES-256-GCM and scrypt."""
    AESGCM, _Scrypt = _require_crypto()
    source = Path(source_path)
    dest = Path(dest_path)
    if not source.is_file():
        raise BackupError('Backup ZIP file was not created.')
    password_bytes = _normalize_password(password)
    if len(password_bytes) < MIN_PASSWORD_LENGTH:
        raise BackupError('Encryption password must be at least %s characters.' % MIN_PASSWORD_LENGTH)

    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_RANDOM_SIZE) + b'\x00\x00\x00\x00'
    header = _build_header(
        salt,
        nonce,
        chunk_size,
        database_name=database_name,
        plan_id=plan_id,
        backup_datetime=backup_datetime,
    )
    length_and_header, header_bytes = _encode_header(header)
    key = _derive_key(password_bytes, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    aesgcm = AESGCM(key)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name('.%s.part' % dest.name)
    try:
        with source.open('rb') as src, tmp_path.open('wb') as out:
            restrict_file_permissions(tmp_path)
            out.write(ENC_MAGIC)
            out.write(length_and_header)
            index = 0
            wrote_chunk = False
            while True:
                plaintext = src.read(chunk_size)
                if not plaintext and wrote_chunk:
                    break
                nonce_i = _chunk_nonce(nonce, index)
                aad = _chunk_aad(header_bytes, index)
                out.write(aesgcm.encrypt(nonce_i, plaintext, aad))
                wrote_chunk = True
                index += 1
                if not plaintext:
                    break
        os.replace(tmp_path, dest)
        restrict_file_permissions(dest)
        validate_encrypted_container(dest)
        return dest
    except BackupError:
        unlink_quietly(tmp_path)
        unlink_quietly(dest)
        raise
    except OSError as exc:
        unlink_quietly(tmp_path)
        unlink_quietly(dest)
        raise BackupError(ENCRYPTION_FAILED_MESSAGE) from exc
    except Exception as exc:
        unlink_quietly(tmp_path)
        unlink_quietly(dest)
        raise BackupError(ENCRYPTION_FAILED_MESSAGE) from exc


def _header_as_manifest(header, filename):
    from odoo.addons.cb_auto_backup_manager.models.backup_utils import (
        MODULE_NAME,
        parse_backup_filename_datetime,
    )
    backup_dt = header.get('backup_datetime')
    if not backup_dt:
        parsed = parse_backup_filename_datetime(filename)
        backup_dt = parsed.isoformat() if parsed else ''
    return {
        'module_name': MODULE_NAME,
        'database_name': header.get('database_name') or '',
        'plan_id': header.get('plan_id'),
        'backup_datetime': backup_dt,
        'encrypted': True,
        'encryption_method': 'aes256',
    }


def identify_encrypted_backup_from_fileobj(fileobj, filename, database_name, plan_id=None, require_plan_id=False):
    from odoo.addons.cb_auto_backup_manager.models.backup_utils import _match_backup_manifest
    try:
        header = read_encrypted_header_from_fileobj(fileobj)
    except BackupError:
        return False, None, 'File is not a valid encrypted backup.'
    if not header.get('database_name'):
        match_name = (filename or '').rsplit('_', 2)
        if match_name:
            header['database_name'] = match_name[0]
    manifest = _header_as_manifest(header, filename)
    return _match_backup_manifest(manifest, database_name, plan_id, require_plan_id)


def identify_encrypted_backup(path, database_name, plan_id=None, require_plan_id=False):
    file_path = Path(path)
    try:
        with file_path.open('rb') as handle:
            return identify_encrypted_backup_from_fileobj(
                handle,
                file_path.name,
                database_name,
                plan_id=plan_id,
                require_plan_id=require_plan_id,
            )
    except OSError:
        return False, None, 'Unable to read encrypted backup.'


def decrypt_backup_file(source_path, dest_path, password):
    """Decrypt an encrypted backup into dest_path (a ZIP)."""
    AESGCM, _Scrypt = _require_crypto()
    source = Path(source_path)
    dest = Path(dest_path)
    try:
        header = validate_encrypted_container(source)
    except BackupError:
        raise

    try:
        salt = bytes.fromhex(header['salt'])
        nonce = bytes.fromhex(header['nonce'])
        chunk_size = int(header['chunk_size'])
        n = int(header.get('kdf_n') or SCRYPT_N)
        r = int(header.get('kdf_r') or SCRYPT_R)
        p = int(header.get('kdf_p') or SCRYPT_P)
        header_bytes = header['_header_bytes']
        header_end = int(header['_header_end'])
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupError(CORRUPT_CONTAINER_MESSAGE) from exc

    password_bytes = _normalize_password(password)
    key = _derive_key(password_bytes, salt, n, r, p)
    aesgcm = AESGCM(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name('.%s.part' % dest.name)
    file_size = source.stat().st_size

    try:
        with source.open('rb') as src, tmp_path.open('wb') as out:
            restrict_file_permissions(tmp_path)
            src.seek(header_end)
            index = 0
            while True:
                remaining = file_size - src.tell()
                if remaining == 0:
                    break
                if remaining < GCM_TAG_SIZE:
                    raise BackupError(CORRUPT_CONTAINER_MESSAGE)
                to_read = min(chunk_size + GCM_TAG_SIZE, remaining)
                packet = src.read(to_read)
                if len(packet) != to_read:
                    raise BackupError(CORRUPT_CONTAINER_MESSAGE)
                nonce_i = _chunk_nonce(nonce, index)
                aad = _chunk_aad(header_bytes, index)
                try:
                    plaintext = aesgcm.decrypt(nonce_i, packet, aad)
                except Exception as exc:
                    raise BackupError(DECRYPT_FAILED_MESSAGE) from exc
                out.write(plaintext)
                index += 1
        os.replace(tmp_path, dest)
        restrict_file_permissions(dest)
        return dest
    except BackupError:
        unlink_quietly(tmp_path)
        unlink_quietly(dest)
        raise
    except OSError as exc:
        unlink_quietly(tmp_path)
        unlink_quietly(dest)
        message = sanitize_error_message(str(exc))
        if 'No space' in message or 'space' in message.lower():
            raise BackupError('Not enough disk space to decrypt the backup.') from exc
        raise BackupError(CORRUPT_CONTAINER_MESSAGE) from exc
