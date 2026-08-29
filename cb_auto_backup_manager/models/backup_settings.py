# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CbBackupSettings(models.TransientModel):
    _name = 'cb.backup.settings'
    _description = 'Auto Backup Manager Settings'
    _rec_name = 'name'

    name = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('name', _('Settings'))
        return super().create(vals_list)

    @api.model
    def action_open_settings(self):
        settings = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settings'),
            'res_model': 'cb.backup.settings',
            'res_id': settings.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'create': False, 'delete': False},
        }

    def action_open_plans(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_plan'
        )

    def action_open_storage(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_storage'
        )

    def action_open_dashboard(self):
        return self.env['cb.backup.dashboard'].action_open_dashboard()

    def action_open_encryption(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'cb_auto_backup_manager.action_cb_backup_encryption_profile'
        )
