{
    "name": "MCP Server for Odoo (Community)",
    "version": "19.0.1.0.0",
    "category": "Productivity/Tools",
    "summary": "Connect Claude, ChatGPT and any MCP client to Odoo 19 Community or Enterprise over a native /mcp endpoint",
    "description": """
MCP Server for Odoo Community
=============================

Odoo 20 ships a native MCP server, but only in Enterprise. This module brings
the same capability to Odoo 19, Community included, with no bridge
process and no middleware: your Odoo instance itself answers Model Context
Protocol requests at ``/mcp``.

Key points
----------
* Streamable HTTP transport, JSON-RPC 2.0, MCP revision 2025-06-18
* Authentication with a dedicated MCP key (stored hashed), never a password
* Explicit model allowlist: nothing is reachable until you enable it
* Per-model read / write / create flags on top of normal Odoo access rights
* Every call runs as the key's owner, so record rules apply unchanged
* Tools: context, list models, inspect fields, search, read, create, update
* Full audit log of every tool call

Security
--------
Access is deny-by-default. An MCP client can only touch models you have
explicitly added to the allowlist, and only with the operations you ticked.
All operations are executed with the permissions of the user who owns the
API key, so a salesperson's key cannot read accounting.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb/mna-odoo-addons",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/mna_mcp_data.xml",
        "wizard/mna_mcp_key_wizard_views.xml",
        "views/mna_mcp_model_views.xml",
        "views/mna_mcp_key_views.xml",
        "views/mna_mcp_log_views.xml",
        "views/mna_mcp_menus.xml",
    ],
    "images": [
        'static/description/01_exposed_models.png',
        'static/description/banner.png',
        'static/description/02_new_key.png',
        'static/description/03_keys.png',
        'static/description/04_call_log.png',
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
