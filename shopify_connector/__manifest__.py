# -*- coding: utf-8 -*-
{
    "name": "Shopify Connector",
    "version": "19.0.1.0.0",
    "category": "Sales",
    "summary": "Foundation for integrating Odoo with Shopify stores",
    "description": """
Shopify Connector
=================

Production-ready foundation for synchronizing Odoo with Shopify.

Configure Shopify store instances per company, manage API credentials and
connection status, and use queue and log infrastructure for future sync
operations.
    """,
    "author": "CodeBraze (PVT) Ltd",
    "website": "https://codebraze.lk",
    "license": "OPL-1",
    "depends": [
        "base",
        "mail",
        "web",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/shopify_instance_views.xml",
        "views/dashboard_views.xml",
        "views/queue_views.xml",
        "views/log_views.xml",
        "views/webhook_views.xml",
        "views/menu.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
