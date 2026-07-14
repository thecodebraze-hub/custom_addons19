# -*- coding: utf-8 -*-
{
    "name": "POS Return Exchange",
    "version": "19.0.1.30.7",
    "category": "Sales/Point of Sale",
    "summary": "POS return and exchange workflows for retail operations",
    "description": """
POS Return Exchange
-------------------

Complete Point of Sale solution for product returns, exchanges, and return
vouchers with inventory, accounting, barcode scanning, thermal receipts,
and analytics reporting.

Features: POS return/exchange screens, voucher payment, credit notes,
stock pickings, audit trail, 58/80 mm receipts, dashboard and Excel/PDF export.
See README.md and docs/ for full documentation.
    """,
    "author": "CodeBraze",
    "website": "https://www.codebraze.com",
    "support": "sales@codebraze.com",
    "price": 74.99,
    "currency": "USD",
    "images": [
        "images/main_screenshot.png",
        "static/description/cover_screenshot.png",
        "static/description/exchange_scan_screenshot.png",
        "static/description/exchange_confirm_screenshot.png",
        "static/description/exchange_voucher_issued_screenshot.png",
        "static/description/exchange_voucher_print_screenshot.png",
        "static/description/order_return_search_screenshot.png",
        "static/description/order_return_lines_screenshot.png",
        "static/description/order_return_receipt_screenshot.png",
        "static/description/order_return_voucher_screenshot.png",
        "static/description/voucher_scan_button_screenshot.png",
        "static/description/voucher_scan_popup_screenshot.png",
        "static/description/voucher_applied_payment_screenshot.png",
        "static/description/voucher_sale_receipt_screenshot.png",
        "static/description/return_settings_screenshot.png",
        "static/description/voucher_report_screenshot.png",
    ],
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "stock",
        "account",
        "product",
        "mail",
        "web",
    ],
    "external_dependencies": {
        "python": ["xlsxwriter"],
    },
    "data": [
        "security/cb_pos_return_exchange_security.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_sequence_data.xml",
        "data/cb_pos_return_config_data.xml",
        "data/ir_cron_data.xml",
        "report/cb_pos_return_paperformat.xml",
        "report/cb_pos_return_receipt_templates.xml",
        "report/cb_pos_return_receipt_reports.xml",
        "views/cb_pos_return_report_views.xml",
        "views/cb_pos_voucher_report_views.xml",
        "views/cb_pos_exchange_report_views.xml",
        "views/cb_pos_sales_return_analysis_views.xml",
        "views/cb_pos_report_dashboard_views.xml",
        "report/cb_pos_analytics_reports.xml",
        "data/cb_pos_report_server_actions.xml",
        "wizards/cb_pos_report_export_wizard_views.xml",
        "views/cb_pos_return_config_views.xml",
        "views/pos_config_views.xml",
        "views/cb_pos_report_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "demo": [
        "demo/cb_pos_return_exchange_demo.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            (
                "after",
                "point_of_sale/static/src/app/services/pos_store.js",
                "cb_pos_return_exchange/static/src/app/load_services.js",
            ),
            (
                "after",
                "point_of_sale/static/src/app/services/pos_store.js",
                "cb_pos_return_exchange/static/src/app/services/pos_store.js",
            ),
            (
                "after",
                "point_of_sale/static/src/app/screens/payment_screen/payment_screen.js",
                "cb_pos_return_exchange/static/src/app/screens/payment_screen/payment_screen.js",
            ),
            (
                "after",
                "point_of_sale/static/src/app/screens/product_screen/control_buttons/control_buttons.js",
                "cb_pos_return_exchange/static/src/app/screens/product_screen/control_buttons/control_buttons.js",
            ),
            "cb_pos_return_exchange/static/src/app/**/*",
        ],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
