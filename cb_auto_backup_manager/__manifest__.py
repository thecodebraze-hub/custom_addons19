# -*- coding: utf-8 -*-
{
    'name': 'CB Auto Backup Manager',
    'version': '19.0.13.0.0',
    'category': 'Administration',
    'summary': 'Automated PostgreSQL and filestore backups with Local, SFTP, and Google Drive storage for Odoo 19',
    'description': """
CB Auto Backup Manager
======================

Back up selected PostgreSQL databases and their Odoo filestore on the same
Odoo server. Deliver verified ZIP or AES-256 encrypted archives to Local
Server, SFTP, and Google Drive destinations, then verify or test-restore without overwriting
the live database.

Implemented:
* Backup Plans with Backups Per Day and daily/weekly/monthly times
* Odoo-compatible ZIP archives (dump.sql + filestore) for Database Manager restore
* Local Server, SFTP, and Google Drive storage
* SHA-256 checksums, ZIP integrity, optional AES-256-GCM encryption
* Retention cleanup, dashboard, native Odoo notifications
* Backup verification and temporary restore testing
    """,
    'author': 'CodeBraze (PVT) Ltd',
    'website': 'https://www.codebraze.com',
    'support': 'info@codebraze.com',
    'license': 'OPL-1',
    'price': 9.99,
    'currency': 'USD',
    'depends': [
        'base',
        'mail',
    ],
    'external_dependencies': {
        'python': ['paramiko'],
    },
    'images': [
        'static/description/banner.png',
        'static/description/screenshot_dashboard.png',
        'static/description/screenshot_plan.png',
        'static/description/screenshot_schedule.png',
        'static/description/screenshot_storage_list.png',
        'static/description/screenshot_sftp.png',
        'static/description/screenshot_history.png',
        'static/description/screenshot_cleanup.png',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/backup_storage_views.xml',
        'views/backup_plan_views.xml',
        'views/backup_schedule_views.xml',
        'views/backup_history_views.xml',
        'views/backup_cleanup_views.xml',
        'views/backup_dashboard_views.xml',
        'views/backup_settings_views.xml',
        'views/backup_restore_views.xml',
        'views/backup_encryption_views.xml',
        'views/menu_views.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
