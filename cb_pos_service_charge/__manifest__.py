{
    "name": "POS Service Charge",
    "version": "19.0.1.0.7",
    "category": "Sales/Point of Sale",
    "summary": "Apply percentage-based service charge to POS orders via button and wizard",
    "description": """
POS Service Charge
------------------

Add a percentage-based service charge to Point of Sale orders from the Actions menu.

* Enable per POS from settings and choose the default rate configuration
* Open Actions → % Service Charge to set or edit the rate with a numpad
* Live preview of order total, service charge amount, and final total
* Service charge appears as an order line and on printed receipts
* Auto-recalculates when products, quantities, prices, or discounts change
* Remove service charge from the same wizard when needed

Compatible with Odoo Community and Enterprise (Point of Sale + Restaurant).
    """,
    "author": "CodeBraze PVT LTD",
    "website": "https://www.codebraze.lk",
    "support": "sales@codebraze.com",
    "images": [
        "images/main_screenshot.png",
        "static/description/cover_screenshot.png",
        "static/description/service_charge_actions_screenshot.png",
        "static/description/service_charge_wizard_screenshot.png",
        "static/description/service_charge_order_screenshot.png",
        "static/description/service_charge_receipt_screenshot.png",
    ],
    "depends": ["point_of_sale", "pos_restaurant"],
    "post_init_hook": "post_init_hook",
    "data": [
        "data/pos_service_charge_data.xml",
        "data/pos_service_charge_assign.xml",
        "security/ir.model.access.csv",
        "views/pos_service_charge_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            (
                "after",
                "pos_restaurant/static/src/app/services/pos_store.js",
                "cb_pos_service_charge/static/src/app/services/pos_store.js",
            ),
            "cb_pos_service_charge/static/src/**/*",
            (
                "after",
                "point_of_sale/static/src/app/screens/receipt_screen/receipt_screen.scss",
                "cb_pos_service_charge/static/src/app/components/popups/service_charge_popup/service_charge_popup.scss",
            ),
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
