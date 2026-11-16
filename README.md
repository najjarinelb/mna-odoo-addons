# mna-odoo-addons

Free, open-source Odoo modules by [Mohammad Najjarine](https://github.com/najjarinelb).
Branch names follow the Odoo series: this is `19.0`.

| Module | What it does |
|---|---|
| [`mna_mcp_server`](mna_mcp_server/) | Native MCP server for Odoo 19, Community included. Connect Claude, ChatGPT or any MCP client at `/mcp`. |

## mna_mcp_server in two minutes

Odoo 20 ships a native MCP server, but only in Enterprise. This module gives Odoo 19 the same capability with no bridge process: Odoo itself answers Model Context Protocol requests.

1. Copy `mna_mcp_server` into your addons path, update the apps list, install **MCP Server for Odoo (Community)**.
2. Open **MCP Server > Exposed Models** and add the models the AI may use. Read is on by default, create and update are per model switches.
3. Open **MCP Server > Keys > New Key**, pick the user the key runs as, copy the key (shown once).
4. Point your MCP client at it:

```json
{
  "mcpServers": {
    "odoo": {
      "type": "http",
      "url": "https://your-odoo.example.com/mcp",
      "headers": { "Authorization": "Bearer mna_xxxxxxxx" }
    }
  }
}
```

Quick check from a terminal:

```bash
curl -s https://your-odoo.example.com/mcp \
  -H "Authorization: Bearer mna_xxxxxxxx" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Security model

- **Deny by default.** A model that is not in the allowlist does not exist as far as the client is concerned.
- **Runs as the key's user.** Access rights and record rules apply unchanged. Exposing a model never grants more than the user already has.
- **Keys are stored hashed**, shown once, can expire, and are revoked by deleting them.
- **No delete tool.** By design.
- **Every call is logged** in MCP Server > Call Log.

### Tools

`get_context`, `list_models`, `get_fields`, `search_records`, `count_records`, `read_records`, `create_record`, `update_record`

### Tests

```bash
odoo-bin -d test_db -i mna_mcp_server --test-tags /mna_mcp_server --stop-after-init
```

## Licence

LGPL-3. See [LICENSE](LICENSE).

## Need something custom?

I build and support Odoo for a living: custom modules, reports, migrations, integrations. Open an issue or reach me through my GitHub profile.
