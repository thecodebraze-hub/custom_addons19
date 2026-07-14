{
    "name": "Bar Liquor Bottle & Shot Inventory",
    "version": "19.0.1.0.8",
    "category": "Inventory/Inventory",
    "summary": "Track opened liquor bottles, ml balances, and POS shot consumption for bars",
    "description": """
Bar Liquor Bottle & Shot Inventory for Odoo 19
================================

Track opened liquor bottles and automatic shot consumption in Point of Sale.

* Mark products as liquor with the Is Liquor checkbox
* Track bottle size, sealed stock, and remaining ml on open bottles
* Link shot products to parent bottles with consumption per sale
* Automatic bottle opening and stock moves when POS orders are paid
* Opened Liquor Bottles register for full audit trail
    """,
    "author": "CodeBraze PVT LTD",
    "website": "https://www.codebraze.lk",
    "support": "sales@codebraze.com",
    "price": 49.99,
    "currency": "USD",
    "images": [
        "images/main_screenshot.png",
        "static/description/cover_screenshot.png",
        "static/description/bar_liquor_inventory_screenshot.png",
    ],
    "depends": ["point_of_sale", "stock_account"],
    "data": [
        "security/ir.model.access.csv",
        "data/sample_products.xml",
        "views/liquor_open_bottle_views.xml",
        "views/product_template_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
