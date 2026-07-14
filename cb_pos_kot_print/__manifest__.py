{
    "name": "POS KOT Print",
    "version": "19.0.1.0.6",
    "category": "Sales/Point of Sale",
    "summary": "Print Kitchen Order Tickets from POS using the receipt printer",
    "author": "CodeBraze",
    "website": "https://www.codebraze.lk",
    "support": "sales@codebraze.com",
    "price": 20.0,
    "currency": "USD",
    "images": [
        "images/main_screenshot.png",
        "static/description/cover_screenshot.png",
        "static/description/kot_button_screenshot.png",
        "static/description/kot_wizard_screenshot.png",
    ],
    "depends": ["point_of_sale", "pos_restaurant", "pos_settle_due"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/product_template_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            (
                "after",
                "pos_restaurant/static/src/app/screens/product_screen/product_screen.js",
                "cb_pos_kot_print/static/src/app/screens/product_screen/product_screen.js",
            ),
            (
                "after",
                "pos_restaurant/static/src/app/services/pos_store.js",
                "cb_pos_kot_print/static/src/app/services/pos_store.js",
            ),
            (
                "after",
                "pos_restaurant/static/src/store/order_change_receipt_template.xml",
                "cb_pos_kot_print/static/src/app/kot_receipt_template.xml",
            ),
            (
                "after",
                "pos_restaurant/static/src/app/screens/product_screen/actionpad_widget/actionpad_widget.xml",
                "cb_pos_kot_print/static/src/app/screens/product_screen/actionpad_widget/actionpad_widget.xml",
            ),
            "cb_pos_kot_print/static/src/**/*",
            (
                "remove",
                "cb_pos_kot_print/static/src/app/screens/partner_list/partner_line_fix.js",
            ),
            (
                "after",
                "pos_settle_due/static/src/app/services/pos_store.js",
                "cb_pos_kot_print/static/src/app/screens/partner_list/partner_line_fix.js",
            ),
            (
                "after",
                "point_of_sale/static/src/css/pos_receipts.css",
                "cb_pos_kot_print/static/src/app/kot_receipt_print.scss",
            ),
            (
                "after",
                "point_of_sale/static/src/app/screens/receipt_screen/receipt_screen.scss",
                "cb_pos_kot_print/static/src/app/components/popups/kot_wizard_popup/kot_wizard_popup.scss",
            ),
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
