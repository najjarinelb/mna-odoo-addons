{
    "name": "Manufacturing Order Check | MO Audit for Zero Cost & Missing Consumption",
    "version": "18.0.1.0.0",
    "category": "Manufacturing/Manufacturing",
    "summary": "The manufacturing orders that closed wrong, consumed nothing, or will cost you nothing",
    "description": """
Manufacturing Order Check
=========================

A manufacturing order can close in a state nobody notices. It produces 90
when it was told to produce 100 and the shortfall never reaches anyone. A
component is on the order and never consumed, so stock stays high and the
cost of what you made is understated. A work centre logs no time at all,
so every hour of labour in that order is free.

None of this throws an error. It shows up weeks later as stock that will
not reconcile and a margin nobody believes.

This is one screen that goes looking for it.

What it checks
--------------
* Produced quantity that does not match the quantity ordered
* Components planned on the order and never consumed
* Components consumed well over plan, past a tolerance you set
* Components with no cost recorded, which understate what you made
* Work orders that logged no time, so labour cost comes out at zero
* Orders finished with no finished-goods movement at all

Quiet when there is nothing wrong
---------------------------------
A check that fires on healthy data gets switched off within a week, so
every rule here is written to stay silent on a clean order. The
over-consumption rule has a tolerance, because scrap is normal and a
report that calls every gram of scrap a problem is noise. Components
marked as flexible consumption on their own bill of materials are not
reported for consuming a different quantity, because that is what the
setting means.

Each finding carries the two numbers behind it, planned and actual, so you
can tell at a glance whether it is worth your morning.

Free and open source, LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://wa.me/96171835279",
    "license": "LGPL-3",
    "depends": ["mrp"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_mrp_order_check_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_findings.png",
        "static/description/02_setup.png",
    ],
    "installable": True,
    "application": False,
}
