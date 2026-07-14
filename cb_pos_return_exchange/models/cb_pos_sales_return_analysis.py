# -*- coding: utf-8 -*-
"""Sales vs return analysis SQL view."""

from odoo import fields, models, tools
from odoo.tools import SQL


class CbPosSalesReturnAnalysis(models.Model):
    _name = "cb.pos.sales.return.analysis"
    _description = "Sales vs Return Analysis"
    _auto = False
    _order = "period_date desc, company_id, config_id"

    period_date = fields.Date(string="Date", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)
    config_id = fields.Many2one("pos.config", string="POS", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)
    sales_amount = fields.Monetary(string="Sales", readonly=True, currency_field="currency_id")
    sales_count = fields.Integer(string="Sales Count", readonly=True)
    return_amount = fields.Monetary(string="Returns", readonly=True, currency_field="currency_id")
    return_count = fields.Integer(string="Return Count", readonly=True)
    net_sales = fields.Monetary(string="Net Sales", readonly=True, currency_field="currency_id")
    return_pct = fields.Float(string="Return %", digits=(16, 2), readonly=True)
    report_count = fields.Integer(string="Count", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL(
            """
            CREATE OR REPLACE VIEW %(table)s AS (
                SELECT
                    ROW_NUMBER() OVER ()::integer AS id,
                    d.period_date,
                    d.company_id,
                    d.config_id,
                    d.currency_id,
                    COALESCE(s.sales_amount, 0.0) AS sales_amount,
                    COALESCE(s.sales_count, 0) AS sales_count,
                    COALESCE(r.return_amount, 0.0) AS return_amount,
                    COALESCE(r.return_count, 0) AS return_count,
                    COALESCE(s.sales_amount, 0.0) - COALESCE(r.return_amount, 0.0) AS net_sales,
                    CASE
                        WHEN COALESCE(s.sales_amount, 0.0) > 0
                        THEN (COALESCE(r.return_amount, 0.0) / s.sales_amount) * 100.0
                        ELSE 0.0
                    END AS return_pct,
                    1 AS report_count
                FROM (
                    SELECT period_date, company_id, config_id, currency_id
                    FROM (
                        SELECT DATE(po.date_order) AS period_date,
                               po.company_id,
                               po.config_id,
                               pc.currency_id
                        FROM pos_order po
                        JOIN pos_config pc ON po.config_id = pc.id
                        WHERE po.state IN ('paid', 'done', 'invoiced')
                          AND po.amount_total >= 0
                        UNION
                        SELECT DATE(ret.create_date) AS period_date,
                               ret.company_id,
                               ret.config_id,
                               ret.currency_id
                        FROM cb_pos_return ret
                        WHERE ret.state = 'done'
                    ) AS activity_dates
                    GROUP BY period_date, company_id, config_id, currency_id
                ) d
                LEFT JOIN (
                    SELECT DATE(po.date_order) AS period_date,
                           po.company_id,
                           po.config_id,
                           pc.currency_id,
                           SUM(po.amount_total) AS sales_amount,
                           COUNT(*) AS sales_count
                    FROM pos_order po
                    JOIN pos_config pc ON po.config_id = pc.id
                    WHERE po.state IN ('paid', 'done', 'invoiced')
                      AND po.amount_total >= 0
                    GROUP BY DATE(po.date_order), po.company_id, po.config_id, pc.currency_id
                ) s ON d.period_date = s.period_date
                   AND d.company_id = s.company_id
                   AND d.config_id = s.config_id
                   AND d.currency_id = s.currency_id
                LEFT JOIN (
                    SELECT DATE(ret.create_date) AS period_date,
                           ret.company_id,
                           ret.config_id,
                           ret.currency_id,
                           SUM(ret.amount_total) AS return_amount,
                           COUNT(*) AS return_count
                    FROM cb_pos_return ret
                    WHERE ret.state = 'done'
                    GROUP BY DATE(ret.create_date), ret.company_id, ret.config_id, ret.currency_id
                ) r ON d.period_date = r.period_date
                   AND d.company_id = r.company_id
                   AND d.config_id = r.config_id
                   AND d.currency_id = r.currency_id
            )
            """,
            table=SQL.identifier(self._table),
        ))
