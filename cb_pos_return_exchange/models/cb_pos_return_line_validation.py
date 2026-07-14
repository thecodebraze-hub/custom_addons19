# -*- coding: utf-8 -*-
"""Return line quantity validation helpers."""

from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

ACTIVE_RETURN_STATES = ("confirmed", "done")


class CbPosReturnLineValidation(models.Model):
    _inherit = "cb.pos.return.line"

    @api.model
    def _get_cumulative_returned_qty(self, order_line_id, exclude_return_id=None):
        """Sum qty already returned on confirmed/done returns for a POS order line."""
        if not order_line_id:
            return 0.0
        domain = [
            ("original_line_id", "=", order_line_id),
            ("return_id.state", "in", ACTIVE_RETURN_STATES),
        ]
        if exclude_return_id:
            domain.append(("return_id", "!=", exclude_return_id))
        groups = self.env["cb.pos.return.line"].read_group(
            domain, ["qty:sum"], ["original_line_id"]
        )
        if not groups:
            return 0.0
        return groups[0].get("qty") or 0.0

    def _validate_line_qty(self):
        """Validate return quantity against sold and previously returned qty."""
        precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        for line in self:
            if float_compare(line.qty, 0.0, precision_digits=precision) <= 0:
                raise ValidationError(line.env._("Return quantity must be positive."))
            if not line.original_line_id:
                raise ValidationError(line.env._("Return line must reference an order line."))
            prior = line._get_cumulative_returned_qty(
                line.original_line_id.id,
                exclude_return_id=line.return_id.id if line.return_id else None,
            )
            remaining = line.qty_sold - prior
            if float_compare(line.qty, remaining, precision_digits=precision) > 0:
                raise ValidationError(
                    line.env._(
                        "Return quantity %(qty)s for %(product)s exceeds remaining "
                        "quantity %(remaining)s.",
                        qty=line.qty,
                        product=line.product_id.display_name,
                        remaining=remaining,
                    )
                )
