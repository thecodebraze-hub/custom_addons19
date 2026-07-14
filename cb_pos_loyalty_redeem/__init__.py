# -*- coding: utf-8 -*-

from . import models


def _post_init_hook(env):
    """Ensure redemption product is saleable and linked on enabled POS configs."""
    product = env.ref(
        "cb_pos_loyalty_redeem.product_product_loyalty_redeem",
        raise_if_not_found=False,
    )
    if product:
        product.write({"sale_ok": True, "purchase_ok": False, "available_in_pos": False})
    for config in env["pos.config"].search([("cb_loyalty_redeem_enabled", "=", True)]):
        if not config.cb_loyalty_redeem_product_id and product:
            config.cb_loyalty_redeem_product_id = product
