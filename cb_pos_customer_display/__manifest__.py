# -*- coding: utf-8 -*-
{
    "name": "POS Loyalty Customer Display",
    "version": "19.0.1.0.5",
    "category": "Sales/Point of Sale",
    "summary": "Let customers search by phone on the POS display and link their profile to the order",
    "description": """
POS Customer Lookup Display
---------------------------


On the POS Customer Display, a customer can type their mobile/phone number,
search matching customers (including loyalty customers), tap their name, and
have that partner set on the cashier's active order.

Works whether the Customer Display runs in the same browser or on a separate
device: search and selection go through the backend (pos.config RPC) and the
selection is pushed to the POS via the bus.

Optional loyalty points display on the customer display (per POS setting).
    """,
    "author": "CodeBraze",
    "website": "https://www.codebraze.com",
    "support": "sales@codebraze.com",
    "price": 35.00,
    "currency": "USD",
    "images": [
        "images/main_screenshot.png",
        "static/description/cover_screenshot.png",
        "static/description/display_search_screenshot.png",
        "static/description/display_selected_screenshot.png",
        "static/description/display_thankyou_screenshot.png",
    ],
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "phone_validation",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "cb_pos_customer_display/static/src/app/**/*",
        ],
        "point_of_sale.customer_display_assets": [
            "cb_pos_customer_display/static/src/customer_display/**/*",
        ],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
