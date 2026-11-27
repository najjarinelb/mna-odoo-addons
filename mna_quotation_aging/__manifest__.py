{
    "name": "Quotation Pipeline Aging | Quote Age, Expiry & Win Rate Report",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "How old the open quotations are, how many expired, who wins and who does not",
    "description": """
Quotation Pipeline Aging
========================

The quotations list in Odoo tells you what is open. It does not tell you
how long it has been open, which is the part that decides whether the
number is a pipeline or a graveyard.

Thirty open quotations reads well until you find that eleven of them are
past their own expiry date, nine have no next step scheduled against
them, and the oldest has been sitting there since March.

This is one screen that answers that, per salesperson.

What it shows
-------------
* Open quotations and their value, in the company's own currency
* Their age in buckets: 0-7, 8-14, 15-30, 31-60 and over 60 days
* The age of the oldest one still open
* How many are past their own expiry date and still open
* How many have no next activity scheduled against them
* Won and lost in the period, and the win rate that follows from it
* A line per salesperson, with a row for quotations nobody owns

Figures that mean something
---------------------------
Totals are converted into the company's currency at each order's own
date, because a pipeline figure that adds a dollar order to a euro one
without converting is a number nobody can use.

A win rate over nothing yet decided is reported as zero wins out of
nothing rather than as a zero percent win rate, because the second reads
as a terrible quarter when it is simply an early one.

Every row opens the quotations behind it, so a number that looks wrong
can be checked rather than argued about.

Read only. It adds no fields to your sales orders and changes nothing.

Runs on Odoo 18 and 19 from one source, on Community and Enterprise
alike. It needs no Enterprise module to work.

Free and open source, LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://wa.me/96171835279",
    "license": "LGPL-3",
    "depends": ["sale_management"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_quotation_aging_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_aging.png",
        "static/description/02_setup.png",
    ],
    "installable": True,
    "application": False,
}
