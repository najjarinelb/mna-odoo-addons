MCP Server for Odoo (Community)
===============================

Odoo 20 ships a native MCP server, but only in Enterprise. This module gives Odoo 18 the same thing, Community included: your Odoo answers Model Context Protocol requests at /mcp, with no bridge process and no middleware.

Features
--------

* **Deny by default**: Nothing is reachable until you add the model to the allowlist. Read, create and update are switched on separately per model.
* **Runs as a real user**: Each key belongs to one Odoo user. Access rights and record rules apply exactly as they do in the interface.
* **Keys, not passwords**: Dedicated MCP keys, stored hashed, shown once, with optional expiry. Delete a key to revoke it instantly.
* **Full audit log**: Every tool call is logged with user, key, model, arguments and outcome.
* **Eight tools**: get_context, list_models, get_fields, search_records, count_records, read_records, create_record, update_record.
* **Standard transport**: Streamable HTTP, JSON-RPC 2.0, MCP revisions 2025-06-18, 2025-03-26 and 2024-11-05.

Usage
-----

#. Install the module and open the MCP Server app.
#. In Exposed Models, add the models the AI may use and tick the operations you allow.
#. In Keys, click New Key, choose the user it runs as, and copy the key.
#. In your MCP client, add a remote server with URL https://your-odoo/mcp and header Authorization: Bearer YOUR-KEY.

Good to know
------------

No delete tool is provided, on purpose. On a multi-database server, the request must reach the right database (dbfilter or a dedicated hostname).

Support
-------

Mohammad Najjarine, https://github.com/najjarinelb
