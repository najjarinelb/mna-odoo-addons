{
    "name": "POS Multi-Currency Payments",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Take Point of Sale payment in a second currency at a rate you control, with the rate kept on every payment",
    "description": """
POS Multi-Currency Payments
===========================

In a dual currency economy the customer pays in whichever note they have,
and the shop keeps its books in one currency. Odoo's Point of Sale takes
payment only in the shop's currency, so the cashier does the arithmetic on
a phone and types the result. That arithmetic is wrong often enough to
matter, and when it is wrong there is no record of what was handed over.

This adds a payment method that takes money in another currency.

How it works
------------
* Set a payment method to a second currency, at the Odoo rate or at a rate
  you fix yourself
* The cashier types what the customer handed over, in that currency
* Odoo records the value in the shop's currency, and keeps both figures
  plus the rate on the payment
* Change is given in the shop's currency by default, because the till
  rarely holds small denominations of the other one
* At closing, the session lists what came in per currency, to count against

Done carefully
--------------
* A fixed rate is the default choice for a reason. A shop with a rate on
  the wall does not want it moving under the cashier because a feed
  updated halfway through the day.
* The conversion is repeated on the server from the rate on the method,
  never trusted from the browser. A till left open since yesterday would
  otherwise book today's takings at yesterday's rate.
* The rate is stored on each payment, so a receipt reprinted next year
  shows the rate that was charged rather than today's.
* Change larger than the sale itself is refused, because that is what a
  rate typed into the amount box looks like.

Works on Odoo 18 and 19, Community and Enterprise.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb",
    "license": "OPL-1",
    "price": 149.0,
    "currency": "USD",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/pos_multi_currency_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "mna_pos_multi_currency/static/src/overrides/pos_payment.js",
            "mna_pos_multi_currency/static/src/overrides/payment_lines.xml",
        ],
    },
    "images": [
        "static/description/banner.png",
        "static/description/01_payment_screen.png",
        "static/description/02_payment_method.png",
    ],
    "installable": True,
    "application": False,
}
