{
    "name": "BoM Where Used Multi-Level | Component Usage & Reverse BoM Report",
    "version": "19.0.1.0.0",
    "category": "Manufacturing/Manufacturing",
    "summary": "Every bill of materials that consumes a component, direct and at any depth",
    "description": """
BoM Where Used (Multi-Level)
============================

Odoo tells you what a bill of materials is made of. It will not tell you
the other way round. Pick a component and there is no screen that answers
"which products would I break if I changed this one". People resort to
exporting every BoM line to a spreadsheet, which only ever answers the
direct level.

This adds that screen, and it climbs.

What it does
------------
* Pick a component, get every BoM that consumes it
* Climbs upward through sub-assemblies to any depth you set
* Quantity of the component per one unit of each parent, rolled through
  every level in between
* The path, so you can see how a screw ends up inside a finished machine
* Works on kits (phantom BoMs) as well as manufactured ones

Why the quantity is the useful part
-----------------------------------
A sub-assembly BoM that produces 2 units and consumes 3 of something uses
1.5 per unit, not 3. Report the line quantity and every roll-up above it
is wrong by the batch size. Here every level is divided by its own BoM
output quantity first, then multiplied up the path, so the number against
a finished product is the quantity you would actually buy.

Unit of measure is handled too: a line in grams against a component held
in kilograms is converted before anything is multiplied.

Loops do not hang it
--------------------
A BoM that reaches itself through a sub-assembly, which happens more often
than anyone admits, is detected and reported as a loop rather than filling
memory. There is a depth limit as well, and a line telling you when the
limit, rather than the data, is what stopped the climb.

Free and open source, LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://wa.me/96171835279",
    "license": "LGPL-3",
    "depends": ["mrp"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_bom_where_used_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_where_used.png",
        "static/description/02_wizard.png",
    ],
    "installable": True,
    "application": False,
}
