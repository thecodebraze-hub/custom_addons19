# -*- coding: utf-8 -*-
{
    "name": "POS Product Card Info",
    "version": "19.0.1.0.1",
    "category": "Sales/Point of Sale",
    "summary": "Show product cost and on-hand quantity via an info icon on POS product cards",
    "description": """
POS Product Card Info
---------------------

Adds a small information icon to the top-right corner of every POS product card.
Tapping it reveals the product's cost and on-hand quantity in a compact popover.

Each piece of information can be enabled independently from the Point of Sale
settings:

* Show product cost
* Show on-hand quantity

For multi-variant products, cost and on-hand quantity are listed per variant.
    """,
    "author": "CodeBraze",
    "website": "https://www.codebraze.lk",
    "support": "sales@codebraze.com",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "stock",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "cb_pos_product_info/static/src/**/*",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
