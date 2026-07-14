# -*- coding: utf-8 -*-

from odoo import fields, models


class CbPosReportExportWizard(models.TransientModel):
    _name = "cb.pos.report.export.wizard"
    _description = "POS Return Report Export Wizard"

    export_format = fields.Selection(
        selection=[
            ("csv", "CSV"),
            ("xlsx", "Excel"),
        ],
        required=True,
        default="xlsx",
    )

    def action_export(self):
        self.ensure_one()
        return self.env["cb.pos.report.export"].with_context(
            self.env.context
        ).action_export_from_context(self.export_format)
