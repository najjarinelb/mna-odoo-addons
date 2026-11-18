{
    "name": "Time Off Balance & Ledger Report",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Time Off",
    "summary": "Allocated, taken, awaiting approval and remaining, per employee and per type, with every movement behind the figure",
    "description": """
Time Off Balance & Ledger Report
================================

Odoo knows the leave balance. It shows it as a number on a card, and when
an employee disputes that number there is no statement to put in front of
them. This builds one.

What you get
------------
* One row per employee and per time off type: allocated, taken, still
  awaiting approval, and remaining
* The movements behind every figure, listed and dated, each with a button
  that opens the allocation or the request itself
* Both days and hours carried on every line, because a type configured in
  hours is meaningless expressed in days
* A choice about pending requests: hold them against the balance, which is
  what an employee planning a trip needs to see, or count only what has
  been approved, which is what a month end accrual needs
* Filter by period, department, employee or type, group it and export it

How the period is read
----------------------
* An allocation counts if it has started by the end of the period and has
  not already ended before the period began. An allocation with no end
  date runs forever, which is how Odoo reads it too.
* A request counts if any part of it falls inside the period.
* Only approved allocations count. A draft allocation is a plan, not a
  balance.

Read only. It reports, it never edits a request or an allocation.

Works on Odoo 18 and 19, Community and Enterprise. Free and open source,
LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb",
    "license": "LGPL-3",
    "depends": ["hr_holidays"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_leave_balance_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_balance.png",
        "static/description/02_ledger.png",
    ],
    "installable": True,
    "application": False,
}
