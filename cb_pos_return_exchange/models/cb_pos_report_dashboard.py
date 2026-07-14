# -*- coding: utf-8 -*-
"""Executive return and exchange dashboard."""

from datetime import timedelta

from odoo import api, fields, models


class CbPosReturnDashboardLine(models.TransientModel):
    _name = "cb.pos.return.dashboard.line"
    _description = "Return Dashboard Chart Line"
    _order = "sequence, id"

    dashboard_id = fields.Many2one(
        comodel_name="cb.pos.return.dashboard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    chart_type = fields.Selection(
        selection=[
            ("return_trend", "Return Trend"),
            ("voucher_liability", "Voucher Liability"),
            ("sales_vs_return", "Sales vs Return"),
            ("top_branch", "Top Branch"),
            ("top_cashier", "Top Cashier"),
            ("top_customer", "Top Customer"),
        ],
        required=True,
    )
    label = fields.Char(required=True)
    count_value = fields.Integer(string="Count")
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="dashboard_id.currency_id",
    )


class CbPosReturnDashboard(models.TransientModel):
    _name = "cb.pos.return.dashboard"
    _description = "Return & Exchange Dashboard"

    date_preset = fields.Selection(
        selection=[
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("this_week", "This Week"),
            ("this_month", "This Month"),
            ("last_month", "Last Month"),
            ("custom", "Custom"),
        ],
        default="this_month",
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        required=True,
    )
    config_id = fields.Many2one(
        comodel_name="pos.config",
        string="POS",
        domain="[('company_id', '=', company_id)]",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="company_id.currency_id",
    )

    returns_count = fields.Integer(readonly=True)
    returns_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    sales_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    return_pct = fields.Float(string="Return %", digits=(16, 2), readonly=True)
    vouchers_outstanding = fields.Monetary(currency_field="currency_id", readonly=True)
    vouchers_issued = fields.Monetary(currency_field="currency_id", readonly=True)
    vouchers_redeemed = fields.Monetary(currency_field="currency_id", readonly=True)
    exchanges_count = fields.Integer(readonly=True)
    pending_returns = fields.Integer(readonly=True)
    avg_return_value = fields.Monetary(currency_field="currency_id", readonly=True)

    line_ids = fields.One2many(
        comodel_name="cb.pos.return.dashboard.line",
        inverse_name="dashboard_id",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        vals.setdefault("date_preset", "this_month")
        vals.setdefault("date_from", today.replace(day=1))
        vals.setdefault("date_to", today)
        return vals

    @api.model
    def action_open_dashboard(self):
        dashboard = self.create({})
        dashboard._load_metrics()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Return & Exchange Dashboard"),
            "res_model": "cb.pos.return.dashboard",
            "view_mode": "form",
            "res_id": dashboard.id,
            "target": "current",
        }

    @api.onchange("date_preset")
    def _onchange_date_preset(self):
        if self.date_preset == "custom":
            return
        today = fields.Date.context_today(self)
        if self.date_preset == "today":
            start = end = today
        elif self.date_preset == "yesterday":
            start = end = today - timedelta(days=1)
        elif self.date_preset == "this_week":
            start = today - timedelta(days=today.weekday())
            end = today
        elif self.date_preset == "last_month":
            first_this = today.replace(day=1)
            end = first_this - timedelta(days=1)
            start = end.replace(day=1)
        else:
            start = today.replace(day=1)
            end = today
        self.date_from = start
        self.date_to = end

    def action_apply_filters(self):
        self.ensure_one()
        self._load_metrics()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Return & Exchange Dashboard"),
            "res_model": "cb.pos.return.dashboard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }

    def _base_domain(self, model_name):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id)]
        if self.config_id:
            if model_name == "cb.pos.return.voucher.redemption":
                domain.append(("voucher_id.config_id", "=", self.config_id.id))
            else:
                domain.append(("config_id", "=", self.config_id.id))
        return domain

    def _date_domain(self, field_name):
        self.ensure_one()
        dt_from = fields.Datetime.to_datetime(self.date_from)
        dt_to = fields.Datetime.to_datetime(self.date_to) + timedelta(days=1, seconds=-1)
        return [(field_name, ">=", dt_from), (field_name, "<=", dt_to)]

    def _load_metrics(self):
        self.ensure_one()
        Return = self.env["cb.pos.return"]
        Voucher = self.env["cb.pos.return.voucher"]
        Exchange = self.env["cb.pos.exchange"]
        Analysis = self.env["cb.pos.sales.return.analysis"]
        Redemption = self.env["cb.pos.return.voucher.redemption"]

        return_domain = self._base_domain("cb.pos.return") + self._date_domain(
            "create_date"
        ) + [("state", "=", "done")]
        returns = Return.search(return_domain)
        returns_count = len(returns)
        returns_amount = sum(returns.mapped("amount_total"))

        analysis_domain = [
            ("company_id", "=", self.company_id.id),
            ("period_date", ">=", self.date_from),
            ("period_date", "<=", self.date_to),
        ]
        if self.config_id:
            analysis_domain.append(("config_id", "=", self.config_id.id))
        analysis_rows = Analysis.search(analysis_domain)
        sales_amount = sum(analysis_rows.mapped("sales_amount"))
        return_pct = (returns_amount / sales_amount * 100.0) if sales_amount else 0.0

        voucher_domain = self._base_domain("cb.pos.return.voucher") + [
            ("state", "in", ("issued", "partial")),
            ("amount_remaining", ">", 0),
        ]
        vouchers_outstanding = sum(
            Voucher.search(voucher_domain).mapped("amount_remaining")
        )

        issued_domain = (
            self._base_domain("cb.pos.return.voucher")
            + self._date_domain("issue_date")
            + [("state", "!=", "cancelled")]
        )
        vouchers_issued = sum(Voucher.search(issued_domain).mapped("amount"))

        redeemed_domain = (
            self._base_domain("cb.pos.return.voucher.redemption")
            + self._date_domain("create_date")
        )
        vouchers_redeemed = sum(Redemption.search(redeemed_domain).mapped("amount"))

        exchange_domain = (
            self._base_domain("cb.pos.exchange")
            + self._date_domain("create_date")
            + [("state", "=", "done")]
        )
        exchanges_count = Exchange.search_count(exchange_domain)

        pending_returns = Return.search_count(
            self._base_domain("cb.pos.return")
            + [("state", "in", ("draft", "confirmed"))]
        )

        avg_return_value = returns_amount / returns_count if returns_count else 0.0

        self.write(
            {
                "returns_count": returns_count,
                "returns_amount": returns_amount,
                "sales_amount": sales_amount,
                "return_pct": return_pct,
                "vouchers_outstanding": vouchers_outstanding,
                "vouchers_issued": vouchers_issued,
                "vouchers_redeemed": vouchers_redeemed,
                "exchanges_count": exchanges_count,
                "pending_returns": pending_returns,
                "avg_return_value": avg_return_value,
            }
        )
        self.line_ids.unlink()
        self._load_chart_lines(return_domain, analysis_domain)

    def _load_chart_lines(self, return_domain, analysis_domain):
        self.ensure_one()
        Return = self.env["cb.pos.return"]
        Analysis = self.env["cb.pos.sales.return.analysis"]
        lines = []
        seq = 10

        def add_rows(chart_type, rows):
            nonlocal seq
            for row in rows:
                lines.append(
                    {
                        "dashboard_id": self.id,
                        "sequence": seq,
                        "chart_type": chart_type,
                        "label": row["label"],
                        "count_value": row.get("count", 0),
                        "amount": row.get("amount", 0.0),
                    }
                )
                seq += 10

        return_groups = Return.read_group(
            return_domain,
            ["amount_total:sum", "report_count:sum"],
            ["return_date:day"],
            lazy=False,
        )
        add_rows(
            "return_trend",
            [
                {
                    "label": g["return_date:day"] or "",
                    "count": g.get("report_count", 0),
                    "amount": g.get("amount_total", 0.0),
                }
                for g in return_groups
            ],
        )

        voucher_groups = self.env["cb.pos.return.voucher"].read_group(
            self._base_domain("cb.pos.return.voucher")
            + [("state", "in", ("issued", "partial"))],
            ["amount_remaining:sum"],
            ["config_id"],
            lazy=False,
        )
        add_rows(
            "voucher_liability",
            [
                {
                    "label": g["config_id"][1] if g.get("config_id") else self.env._("N/A"),
                    "amount": g.get("amount_remaining", 0.0),
                }
                for g in voucher_groups
            ],
        )

        analysis_groups = Analysis.read_group(
            analysis_domain,
            ["sales_amount:sum", "return_amount:sum"],
            ["period_date:week"],
            lazy=False,
        )
        add_rows(
            "sales_vs_return",
            [
                {
                    "label": g["period_date:week"] or "",
                    "amount": g.get("return_amount", 0.0),
                    "count": int(g.get("sales_amount", 0.0)),
                }
                for g in analysis_groups
            ],
        )

        branch_groups = Return.read_group(
            return_domain,
            ["amount_total:sum"],
            ["config_id"],
            lazy=False,
        )
        branch_groups.sort(key=lambda g: g.get("amount_total", 0.0), reverse=True)
        add_rows(
            "top_branch",
            [
                {
                    "label": g["config_id"][1] if g.get("config_id") else self.env._("N/A"),
                    "amount": g.get("amount_total", 0.0),
                }
                for g in branch_groups[:10]
            ],
        )

        cashier_groups = Return.read_group(
            return_domain,
            ["amount_total:sum"],
            ["cashier_id"],
            lazy=False,
        )
        cashier_groups.sort(key=lambda g: g.get("amount_total", 0.0), reverse=True)
        add_rows(
            "top_cashier",
            [
                {
                    "label": g["cashier_id"][1] if g.get("cashier_id") else self.env._("N/A"),
                    "amount": g.get("amount_total", 0.0),
                }
                for g in cashier_groups[:10]
            ],
        )

        customer_groups = Return.read_group(
            return_domain,
            ["amount_total:sum"],
            ["partner_id"],
            lazy=False,
        )
        customer_groups.sort(key=lambda g: g.get("amount_total", 0.0), reverse=True)
        add_rows(
            "top_customer",
            [
                {
                    "label": g["partner_id"][1] if g.get("partner_id") else self.env._("Walk-in"),
                    "amount": g.get("amount_total", 0.0),
                }
                for g in customer_groups[:10]
            ],
        )

        if lines:
            self.env["cb.pos.return.dashboard.line"].create(lines)

    def action_open_returns(self):
        self.ensure_one()
        domain = self._base_domain("cb.pos.return") + self._date_domain("create_date")
        return self._open_window("cb.pos.return", _("Returns"), domain)

    def action_open_vouchers(self):
        self.ensure_one()
        domain = self._base_domain("cb.pos.return.voucher") + [
            ("state", "in", ("issued", "partial")),
            ("amount_remaining", ">", 0),
        ]
        return self._open_window("cb.pos.return.voucher", _("Outstanding Vouchers"), domain)

    def action_open_exchanges(self):
        self.ensure_one()
        domain = (
            self._base_domain("cb.pos.exchange")
            + self._date_domain("create_date")
            + [("state", "=", "done")]
        )
        return self._open_window("cb.pos.exchange", _("Exchanges"), domain)

    def action_open_sales_vs_return(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("period_date", ">=", self.date_from),
            ("period_date", "<=", self.date_to),
        ]
        if self.config_id:
            domain.append(("config_id", "=", self.config_id.id))
        return self._open_window(
            "cb.pos.sales.return.analysis",
            _("Sales vs Return Analysis"),
            domain,
            view_mode="graph,pivot,list",
        )

    def _open_window(self, model, title, domain, view_mode="list,pivot,graph"):
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": model,
            "view_mode": view_mode,
            "domain": domain,
        }
