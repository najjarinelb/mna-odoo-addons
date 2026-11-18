{
    "name": "POS Sales Insight",
    "version": "18.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "POS reporting with margin, discount cost and peak hours, which the standard report does not carry",
    "description": """
POS Sales Insight
=================

Odoo's own Point of Sale report tells you what you sold. It does not tell
you what you made on it, what the discounts cost, or when the shop is
actually busy. This adds one report that does, alongside the standard one
rather than replacing it.

What it adds
------------
* Margin and margin percent per line, from the cost actually recorded
* What discounts cost you, in money rather than in percent
* Hour of day and day of week, so you can staff against the real peak
* Cashier, product, category, customer and point of sale, in a pivot

Peak hours done properly
------------------------
The hour is computed per row in the timezone of the order's own company,
not in UTC. A shop in Beirut that is busiest at 7pm shows a peak at 17:00
in a UTC report, and someone will build next month's rota on that.

Honest about missing costs
--------------------------
A POS line with no cost recorded has a margin equal to its whole revenue,
which flatters any total it lands in. Those lines are marked, and there is
a filter to find them, so you can see whether a flattering margin is real.

Free and open source, LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_pos_insight_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_insight.png",
        "static/description/02_busy.png",
    ],
    "installable": True,
    "application": False,
}
