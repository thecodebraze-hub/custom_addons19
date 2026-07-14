# -*- coding: utf-8 -*-
"""Excel and CSV export helpers for return and exchange reports."""

import base64
import csv
import io
from datetime import datetime

from odoo import _, api, models
from odoo.exceptions import UserError


class CbPosReportExport(models.AbstractModel):
    _name = "cb.pos.report.export"
    _description = "POS Return Report Export Service"

    MAX_ROWS = 50000

    @api.model
    def _attachment_action(self, data, filename, mimetype):
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(data),
                "mimetype": mimetype,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    @api.model
    def _resolve_domain(self, model_name):
        domain = list(self.env.context.get("active_domain") or [])
        active_ids = self.env.context.get("active_ids")
        if active_ids:
            domain = domain + [("id", "in", active_ids)]
        elif not domain:
            domain = []
        return domain

    @api.model
    def _serialize_value(self, value):
        if hasattr(value, "display_name"):
            return value.display_name
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return value or ""

    @api.model
    def export_csv(self, model_name, domain, field_names, title="report"):
        records = self.env[model_name].search(domain, limit=self.MAX_ROWS + 1)
        if len(records) > self.MAX_ROWS:
            raise UserError(
                _("Export exceeds the maximum of %(max)s rows.", max=self.MAX_ROWS)
            )
        fields_meta = self.env[model_name].fields_get(field_names)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([fields_meta[f].get("string", f) for f in field_names])
        for record in records:
            writer.writerow(
                [self._serialize_value(record[fname]) for fname in field_names]
            )
        filename = "%s_%s.csv" % (title, datetime.now().strftime("%Y%m%d_%H%M%S"))
        return self._attachment_action(
            buffer.getvalue().encode("utf-8"), filename, "text/csv"
        )

    @api.model
    def export_xlsx(self, model_name, domain, field_names, title="report"):
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("xlsxwriter is required for Excel export.")) from None

        records = self.env[model_name].search(domain, limit=self.MAX_ROWS + 1)
        if len(records) > self.MAX_ROWS:
            raise UserError(
                _("Export exceeds the maximum of %(max)s rows.", max=self.MAX_ROWS)
            )
        fields_meta = self.env[model_name].fields_get(field_names)
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        sheet = workbook.add_worksheet(title[:31])
        header_fmt = workbook.add_format({"bold": True})
        for col, fname in enumerate(field_names):
            sheet.write(0, col, fields_meta[fname].get("string", fname), header_fmt)
        for row_idx, record in enumerate(records, start=1):
            for col, fname in enumerate(field_names):
                sheet.write(row_idx, col, self._serialize_value(record[fname]))
        workbook.close()
        filename = "%s_%s.xlsx" % (title, datetime.now().strftime("%Y%m%d_%H%M%S"))
        return self._attachment_action(
            buffer.getvalue(),
            filename,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @api.model
    def action_export_from_context(self, export_format="xlsx"):
        ctx = self.env.context
        model_name = ctx.get("report_model") or ctx.get("active_model")
        field_names = ctx.get("report_fields") or []
        title = ctx.get("report_title") or model_name or "report"
        if not model_name or not field_names:
            raise UserError(_("Report export is not configured for this action."))
        domain = self._resolve_domain(model_name)
        if export_format == "xlsx":
            return self.export_xlsx(model_name, domain, field_names, title=title)
        return self.export_csv(model_name, domain, field_names, title=title)
