{
    "name": "Odoo Health Check",
    "version": "19.0.1.0.0",
    "category": "Productivity/Tools",
    "summary": "One screen for the things that quietly break: failed scheduled actions, stuck emails, database size and growth",
    "description": """
Odoo Health Check
=================

Scheduled actions fail silently. Emails sit in the queue for weeks. The
database doubles in size and nobody notices until the server fills up.
None of this is visible anywhere in standard Odoo without digging through
Technical menus one at a time.

This module puts it on one screen.

What it checks
--------------
* Scheduled actions that are inactive, overdue, or have failed
* Outgoing emails stuck in the queue or marked as failed
* Database size, and the ten largest tables
* Attachments stored in the database rather than on disk
* Modules installed but no longer available in the addons path
* Users who have never logged in, and administrators

Every check reports ok, warning or problem, with the count and a button
that opens the records behind it, so you can go and fix what it found.

Nothing is sent anywhere. The report runs on demand, reads only, and
stays inside your database.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb/mna-odoo-addons",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_health_check_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_health_report.png",
        "static/description/02_failed_emails.png",
    ],
    "installable": True,
    "application": True,
}
