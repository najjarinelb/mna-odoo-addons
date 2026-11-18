{
    "name": "POS Session Check",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Find the Point of Sale sessions that closed short, stayed open, or never reached your accounts",
    "description": """
POS Session Check
=================

A Point of Sale closes dozens of sessions a month and Odoo tells you about
none of them. This adds one screen that answers the questions a shop owner
actually asks at the end of the month.

What it checks
--------------
* Sessions left open, with how long, because an open session holds its
  takings out of the ledger
* Closing cash differences above a threshold you set
* Whether those differences follow one person, counted across sessions
* Orders left unpaid in a closed session
* Orders marked to invoice that never got an invoice
* Closed sessions whose journal entry is still in draft
* Orders where what was paid does not match what was charged
* Negative lines that are not linked to the order they refund

Every result links straight to the records behind it.

Written carefully
-----------------
* Thresholds are yours to set. A shop trading past midnight has an open
  session every morning, and a report that calls that a problem is a report
  nobody reads twice.
* The repeat difference check counts three or more sessions before it says
  anything, and says plainly that a shared till looks the same as a
  dishonest one. It is a prompt for a conversation, not an accusation.
* Read only. It reports, it never corrects.

Free and open source, LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_pos_check_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_check.png",
    ],
    "installable": True,
    "application": False,
}
