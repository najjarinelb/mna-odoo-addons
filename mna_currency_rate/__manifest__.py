{
    "name": "Currency Rate Auto Update | Daily ECB Exchange Rates for Odoo Community",
    "version": "19.0.1.0.0",
    "summary": "Daily exchange rates from the ECB and other free providers, "
               "for Odoo Community",
    "description": """
Currency Rate Auto Update
=========================

Automatic exchange rates for Odoo Community.

Odoo ships automatic rate updates only in Enterprise. On Community,
every company running more than one currency has to type rates in by
hand, or quietly let them go stale, which puts the error into every
invoice, every valuation and every report that touches a foreign
currency.

This module fetches rates on a schedule from free providers that need
no account and no API key.

Providers
---------

* European Central Bank, the daily reference rates
* Frankfurter, an ECB mirror with a JSON API
* Open Exchange Rates API, a free USD based feed

Each one is free to use and requires no registration.

What it does properly
---------------------

* Rebases correctly onto your company currency. The ECB publishes
  everything against the euro; if your company runs in dollars, naive
  modules store the euro rate and every conversion is wrong. This one
  divides through by your own currency's rate.
* Updates only the currencies you have actually activated.
* Writes one rate per currency per day, and updates it rather than
  piling duplicates into the table.
* Keeps a log of every run, so a provider that quietly started failing
  three weeks ago is visible instead of silent.
* Never wipes a good rate because a fetch failed.

Multi-company
-------------
Each company chooses its own provider and schedule, and rates are
written against that company's own currency.
""",
    "author": "Mohammad Najjarine",
    "website": "https://wa.me/96171835279",
    "license": "LGPL-3",
    "category": "Accounting/Accounting",
    "depends": ["base", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/currency_rate_log_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_settings.png",
        "static/description/02_updates.png",
        "static/description/03_currencies.png",
    ],
    "installable": True,
    "application": False,
}
