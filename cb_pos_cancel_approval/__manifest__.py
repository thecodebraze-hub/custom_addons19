# -*- coding: utf-8 -*-
{
    "name": "POS Manager Cancel Order Approval",
    "version": "19.0.1.0.5",
    "category": "Sales/Point of Sale",
    "summary": "Require manager PIN and reason before cancelling a POS order or removing lines",
    "description": """
POS Manager Cancel Order Approval
-------------------

When a cashier tries to cancel (delete) a POS order that has items, or remove
order lines (including via backspace), a manager PIN and a reason must be
entered to approve the action.

* Enable/disable per point of sale from the POS settings.
* Approvers set their own approval PIN on their user record.
* Empty orders (no items) can still be discarded without approval.
* Approved cancellations and line removals are stored in an audit log.
    """,
    "author": "CodeBraze",
    "website": "https://www.codebraze.lk",
    "support": "sales@codebraze.com",
    "price": 24.99,
    "currency": "USD",
    "images": [
        "images/main_screenshot.png",
        "static/description/cover_screenshot.png",
        "static/description/pos_settings_screenshot.png",
        "static/description/cancel_order_actions_screenshot.png",
        "static/description/remove_item_approval_screenshot.png",
    ],
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
    ],
    "data": [
        "security/cancel_approval_security.xml",
        "security/ir.model.access.csv",
        "views/res_users_views.xml",
        "views/res_config_settings_views.xml",
        "views/cb_pos_cancel_log_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "cb_pos_cancel_approval/static/src/**/*",
        ],
    },
    "application": True,
    "installable": True,
    "auto_install": False,
}
