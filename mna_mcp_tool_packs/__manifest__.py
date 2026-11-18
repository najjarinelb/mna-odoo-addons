{
    "name": "MCP Tool Packs for Odoo",
    "version": "19.0.1.0.0",
    "category": "Productivity/Tools",
    "summary": "Sales, accounting, inventory and purchase tools for the MCP server, so an AI client gets exact totals instead of adding records up itself",
    "description": """
MCP Tool Packs
==============

An extension for *MCP Server for Odoo*. The server on its own gives an AI
client generic CRUD: search, read, create, update. That answers "find invoice
INV/2026/0042" well, and answers "what did we sell last month by salesperson"
badly, because the model has to page through hundreds of records and add them
up itself. It will do that, and it will be wrong by a page.

This module adds tools that aggregate inside PostgreSQL and return one short,
exact answer.

Tools
-----
Sales (requires *Sales*)

* ``sales_summary`` confirmed sales for a period, grouped by salesperson,
  customer, product, team or month
* ``sales_pipeline`` open quotations and orders with their age in days

Accounting (requires *Invoicing*)

* ``aged_receivable`` customer balances in the usual aging buckets
* ``unpaid_invoices`` posted invoices not fully paid, with days overdue
* ``revenue_by_period`` invoiced totals per month, quarter or year, net of
  credit notes

Inventory (requires *Inventory*)

* ``stock_on_hand`` quantity on hand per product, by location if you want
* ``low_stock`` products at or below their reorder minimum, with incoming
  quantities

Purchase (requires *Purchase*)

* ``purchase_summary`` confirmed purchases grouped by vendor, product, buyer
  or month

Security
--------
Nothing here widens what the MCP server can reach. Every pack tool goes
through the same allowlist as the core tools, so ``aged_receivable`` stays
unavailable until you expose ``account.move.line`` for reading. All tools are
read only and run as the key's own user, so record rules and multi-company
rules apply exactly as they do in the interface.

A pack is hidden from ``tools/list`` when the app it reports on is not
installed, so the client is never offered a tool that cannot work.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb/mna-odoo-addons",
    "license": "LGPL-3",
    "depends": ["mna_mcp_server"],
    "data": [],
    "images": [
        "static/description/banner.png",
        "static/description/01_tools.png",
        "static/description/02_call_log.png",
        "static/description/03_answer.png",
        "static/description/04_exposed_models.png",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
