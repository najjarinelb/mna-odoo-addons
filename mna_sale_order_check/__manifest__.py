{
    "name": "Sales Order Check",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "The sales orders sold under cost, discounted past the limit, delivered and never invoiced",
    "description": """
Sales Order Check
=================

A sales order can go wrong quietly. A line goes out at a price under what
the goods cost and the loss never surfaces until somebody adds up the
year. A discount of forty percent is entered because the customer pushed
and nobody was asked. Goods ship and the invoice is never raised, so the
revenue is real and the receivable is not.

None of this throws an error in Odoo. It turns up a quarter later as a
margin nobody believes and a debtors list that is missing money.

This is one screen that goes looking for it.

What it checks
--------------
* Lines sold under cost, after the discount, with the loss worked out
* Lines discounted past a limit you set, with the amount given up
* Lines sitting at a price of zero that nobody meant to give away
* Orders delivered and still not invoiced once a grace period has run out
* Lines invoiced for more than was ever delivered
* Quotations past their own validity date, still open
* Confirmed orders with no salesperson, which land in nobody's figures

Quiet when there is nothing wrong
---------------------------------
A check that fires on healthy data gets switched off within a week, so
every rule here is written to stay silent on a clean order.

The discount rule has a limit you set, because a company that allows ten
percent does not want a report about ten percent. Invoicing has a grace
period, because invoicing runs on a cycle and a report that flags
yesterday's delivery is noise. A line deliberately given away is entered
as a full discount, so a zero price with a discount on it is left alone
and only a price that was never filled in is reported. A line whose cost
is recorded as zero is not called a loss, because there is nothing to
compare it against. Services and anything invoiced on the ordered
quantity are not measured against what was delivered, because for those
that is not what invoicing follows.

Each finding carries the two numbers behind it, so you can tell at a
glance whether it is worth your morning.

Costs come from the per-line purchase price when Sales Margin is
installed, which is the cost as at the order rather than today's. Without
it the product's current cost is used, converted into the unit of measure
the line was sold in.

Runs on Odoo 18 and 19 from one source. Community only, no Enterprise
dependency.

Free and open source, LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb",
    "license": "LGPL-3",
    "depends": ["sale_management"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_sale_order_check_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_findings.png",
        "static/description/02_setup.png",
    ],
    "installable": True,
    "application": False,
}
