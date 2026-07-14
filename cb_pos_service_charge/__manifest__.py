{
    "name": "POS Service Charge",
    "version": "19.0.1.0.4",
    "category": "Sales/Point of Sale",
    "summary": "Apply percentage-based service charge to POS orders via button and wizard",
    "author": "CodeBraze",
    "website": "https://www.codebraze.lk",
    "support": "sales@codebraze.com",
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
