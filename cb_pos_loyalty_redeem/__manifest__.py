# -*- coding: utf-8 -*-
{
    "name": "POS Loyalty Redemption",
    "version": "19.0.1.0.5",
    "category": "Sales/Point of Sale",
    "summary": "Redeem a custom amount of a customer's loyalty points at the POS",
    "description": """
POS Loyalty Redemption
----------------------

Standard Odoo POS loyalty only lets customers claim pre-configured rewards. This
module adds a "Redeem Points" action so a cashier can redeem any amount of a
customer's available loyalty points as a discount on the current order.

* Enable per point of sale, choose the loyalty program and the point value rate.
* Shows the selected customer's available points (live from the server).
* Validates the requested points against the balance and the order total.
* Adds a negative "Loyalty Redemption" line to the order.
* Deducts points from the loyalty card (with history) once the order is paid,
  and restores them if the order is cancelled.
    """,
    "author": "CodeBraze",
    "website": "https://www.codebraze.lk",
    "support": "sales@codebraze.com",
    "price": 43.00,
    "currency": "USD",
    "images": [
        "images/main_screenshot.png",
        "static/description/cover_screenshot.png",
        "static/description/loyalty_settings_screenshot.png",
        "static/description/redeem_points_actions_screenshot.png",
        "static/description/redeem_wizard_screenshot.png",
        "static/description/redeem_applied_order_screenshot.png",
        "static/description/loyalty_card_screenshot.png",
    ],
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "pos_loyalty",
    ],
    "data": [
        "data/loyalty_redeem_product.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "cb_pos_loyalty_redeem/static/src/**/*",
        ],
    },
    "post_init_hook": "_post_init_hook",
    "application": True,
    "installable": True,
    "auto_install": False,
}
