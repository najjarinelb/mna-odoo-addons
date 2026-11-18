{
    "name": "POS X/Z Report & Daily Closing",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "The end of day report Odoo's Point of Sale does not have: sales, tax breakdown, payment methods, cash reconciliation, numbered and kept",
    "description": """
POS X/Z Report & Daily Closing
==============================

Ask an Odoo Point of Sale for the end of day report and there is nothing
to print. In a good many countries that report is the document an
inspector asks for, and everywhere else it is what the owner reads before
deciding whether the till balanced.

This adds both reports a till needs.

The X report
------------
A look at a session that is still trading. Take it as often as you like,
at a shift change or over a coffee. It changes nothing and it is not
numbered.

The Z report
------------
Closes the day. Taken once per session, numbered in an unbroken sequence,
and kept exactly as it was taken.

What is on them
---------------
* Orders, refunds, items sold and the average basket
* Gross sales, discount given, net, tax, and the total taken
* A line per payment method, including the ones nobody used
* Base and tax per rate, computed the way the order itself was
* Sales per product category
* Cash reconciliation: opening float, cash taken, money in, money out,
  expected, counted, and the difference

Done carefully
--------------
* A Z report cannot be taken twice for the same session, cannot be edited
  and cannot be deleted, because a numbered sequence with a hole in it is
  worse than no sequence at all. You can still add a note.
* A Z report needs a closed session. An X report is for a till that is
  still trading, and reports no cash difference, because nothing has been
  counted yet and a difference there would be noise.
* Payment methods that took nothing are listed at zero. A report with a
  method missing reads as an omission.
* Discount is measured as the gap between list price and what was
  charged, which is the only definition that survives a line discounted
  twice or priced by a pricelist.

Works on Odoo 18 and 19, Community and Enterprise.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb",
    "license": "OPL-1",
    "price": 169.0,
    "currency": "USD",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "data/mna_pos_zreport_data.xml",
        "report/mna_pos_zreport_report.xml",
        "views/mna_pos_zreport_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_zreport.png",
        "static/description/02_cash.png",
        "static/description/03_list.png",
        "static/description/04_tax.png",
    ],
    "installable": True,
    "application": False,
}
