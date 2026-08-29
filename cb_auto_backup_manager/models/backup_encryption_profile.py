# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.cb_auto_backup_manager.models.backup_encryption import (
    MIN_PASSWORD_LENGTH,
)

ENCRYPTION_SECRET_MASK = '********'
ADMIN_GROUP = 'cb_auto_backup_manager.group_cb_backup_administrator'


class CbBackupEncryptionProfile(models.Model):
    _name = 'cb.backup.encryption.profile'
    _description = 'Backup Encryption Profile'
    _order = 'name, id'

    name = fields.Char(
        required=True,
        help='Descriptive name, for example Production Encryption.',
    )
    active = fields.Boolean(default=True)
    method = fields.Selection(
        selection=[
            ('aes256', 'AES-256'),
        ],
        string='Method',
        required=True,
        default='aes256',
    )
    description = fields.Text()
    secret = fields.Char(
        string='Password',
        copy=False,
        groups=ADMIN_GROUP,
    )
    secret_confirm = fields.Char(
        string='Confirm Password',
        compute='_compute_secret_confirm',
        inverse='_inverse_secret_confirm',
        groups=ADMIN_GROUP,
    )
    has_secret = fields.Boolean(
        string='Password Set',
        compute='_compute_has_secret',
    )
    disaster_recovery_warning = fields.Text(
        compute='_compute_disaster_recovery_warning',
    )

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        'An encryption profile with this name already exists.',
    )

    def _compute_secret_confirm(self):
        for profile in self:
            profile.secret_confirm = False

    def _inverse_secret_confirm(self):
        return

    def _compute_has_secret(self):
        stored = {}
        ids = [profile.id for profile in self if profile.id]
        if ids:
            self.env.cr.execute(
                """
                SELECT id, CASE WHEN COALESCE(secret, '') = '' THEN FALSE ELSE TRUE END
                  FROM cb_backup_encryption_profile
                 WHERE id IN %s
                """,
                [tuple(ids)],
            )
            stored = {row[0]: bool(row[1]) for row in self.env.cr.fetchall()}
        for profile in self:
            profile.has_secret = stored.get(profile.id, False)

    def _compute_disaster_recovery_warning(self):
        warning = _(
            'Store the encryption secret securely outside this Odoo server. '
            'If the secret is lost, encrypted backups cannot be restored. '
            'CodeBraze cannot recover an encrypted backup if the encryption '
            'secret is permanently lost.'
        )
        for profile in self:
            profile.disaster_recovery_warning = warning

    @api.model_create_multi
    def create(self, vals_list):
        self._check_admin_access()
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            secret = vals.get('secret')
            confirm = vals.pop('secret_confirm', None)
            self._assert_secret_pair(secret, confirm, required=True)
            prepared.append(vals)
        return super().create(prepared)

    def write(self, vals):
        self._check_admin_access()
        vals = dict(vals)
        if 'secret' in vals or 'secret_confirm' in vals:
            secret = vals.get('secret')
            confirm = vals.pop('secret_confirm', None)
            if secret in (None, False, '', ENCRYPTION_SECRET_MASK):
                vals.pop('secret', None)
            else:
                self._assert_secret_pair(secret, confirm, required=True)
        return super().write(vals)

    def unlink(self):
        self._check_admin_access()
        plans = self.env['cb.backup.plan'].sudo().search([
            ('encryption_profile_id', 'in', self.ids),
            ('encryption_enabled', '=', True),
        ])
        if plans:
            raise UserError(_(
                'Cannot delete an encryption profile that is used by an encrypted backup plan.'
            ))
        return super().unlink()

    def read(self, fields=None, load='_classic_read'):
        rows = super().read(fields, load=load)
        if self.env.context.get('cb_backup_unlock_encryption_secret'):
            return rows
        for row in rows:
            if row.get('secret'):
                row['secret'] = ENCRYPTION_SECRET_MASK
        return rows

    def web_read(self, specification):
        result = super().web_read(specification)
        if self.env.context.get('cb_backup_unlock_encryption_secret'):
            return result
        for row in result:
            if row.get('secret'):
                row['secret'] = ENCRYPTION_SECRET_MASK
        return result

    def export_data(self, fields_to_export):
        data = super().export_data(fields_to_export)
        secret_indexes = [
            index for index, name in enumerate(fields_to_export)
            if name in ('secret', 'secret_confirm')
        ]
        for row in data.get('datas') or []:
            for index in secret_indexes:
                if index < len(row):
                    row[index] = ''
        return data

    def _get_plaintext_secret(self):
        """Server-side only. Never expose over RPC or in views."""
        self.ensure_one()
        if not self.id:
            return False
        self.env.cr.execute(
            'SELECT secret FROM cb_backup_encryption_profile WHERE id = %s',
            [self.id],
        )
        row = self.env.cr.fetchone()
        return row[0] if row else False

    def _assert_secret_pair(self, secret, confirm, required=False):
        if not secret:
            if required:
                raise ValidationError(_('An encryption password is required.'))
            return
        if secret == ENCRYPTION_SECRET_MASK:
            return
        if confirm is None:
            raise ValidationError(_('Confirm the encryption password.'))
        if secret != confirm:
            raise ValidationError(_('The encryption password and confirmation do not match.'))
        if len(secret) < MIN_PASSWORD_LENGTH:
            raise ValidationError(_(
                'Encryption password must be at least %s characters.'
            ) % MIN_PASSWORD_LENGTH)

    def _check_admin_access(self):
        if not self.env.su and not self.env.user.has_group(ADMIN_GROUP):
            raise AccessError(_('Only Backup Administrators can manage encryption profiles.'))
