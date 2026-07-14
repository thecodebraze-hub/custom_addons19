# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Ensure Loyalty Redemption product stays usable in POS sessions."""
    cr.execute(
        """
        UPDATE product_template pt
           SET sale_ok = TRUE,
               purchase_ok = FALSE,
               available_in_pos = FALSE
          FROM product_product pp
         WHERE pp.product_tmpl_id = pt.id
           AND pp.default_code = 'LOYALTY_REDEEM'
        """
    )
