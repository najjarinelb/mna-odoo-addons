{
    "name": "Sequence Gap & Duplicate Report",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Find missing and duplicated numbers in invoice and journal entry sequences, for audit and VAT compliance",
    "description": """
Sequence Gap & Duplicate Report
===============================

Tax authorities in the Gulf, and auditors almost everywhere, expect
invoice numbering to be unbroken: no missing numbers, no repeats. Odoo
numbers documents well, but it gives you no way to prove it, and gaps do
appear in practice, usually from deleted drafts, a reset sequence, or a
number assigned manually.

This module checks, for any journal and any period:

* **Gaps**: numbers that should exist between the first and last document
  but do not
* **Duplicates**: the same number used more than once. Odoo's own unique
  index already prevents this among posted documents, so in practice this
  catches a draft reusing a posted number, and data migrated in from
  another system
* **Out of order dates**: a later number carrying an earlier date, which
  auditors query as often as gaps

It groups documents by their real prefix, so a sequence that changes
yearly or monthly is understood rather than reported as one huge gap.

Read-only. It changes nothing, posts nothing, and renumbers nothing.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb/mna-odoo-addons",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/mna_sequence_gap_wizard_views.xml",
        "views/mna_sequence_gap_views.xml",
    ],
    "images": [
        'static/description/01_sequence_report.png',
        'static/description/banner.png',
    ],
    "installable": True,
    "application": False,
}
