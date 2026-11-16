import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMcp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "MCP Tester",
                "login": "mcp_tester",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("base.group_partner_manager").id])],
            }
        )
        _rec, cls.key = cls.env["mna.mcp.key"]._generate("test", cls.user)
        cls.rule = cls.env["mna.mcp.model"]._get_rule("res.partner")
        cls.partner = cls.env["res.partner"].create({"name": "MCP Partner X1"})

    def _rpc(self, method, params=None, key=None, rpc_id=1):
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if rpc_id is not None:
            body["id"] = rpc_id
        headers = {"Content-Type": "application/json"}
        token = self.key if key is None else key
        if token:
            headers["Authorization"] = "Bearer %s" % token
        return self.url_open("/mcp", data=json.dumps(body), headers=headers)

    def _call(self, name, arguments=None):
        res = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        self.assertEqual(res.status_code, 200)
        result = res.json()["result"]
        text = result["content"][0]["text"]
        return result["isError"], (text if result["isError"] else json.loads(text))

    def test_auth_required(self):
        self.assertEqual(self._rpc("ping", key="").status_code, 401)
        self.assertEqual(self._rpc("ping", key="mna_wrong").status_code, 401)

    def test_handshake(self):
        res = self._rpc("initialize", {"protocolVersion": "2025-06-18"}).json()
        self.assertEqual(res["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", res["result"]["capabilities"])
        self.assertEqual(self._rpc("notifications/initialized", rpc_id=None).status_code, 202)
        tools = self._rpc("tools/list").json()["result"]["tools"]
        self.assertIn("search_records", [t["name"] for t in tools])
        self.assertEqual(self._rpc("nope").json()["error"]["code"], -32601)

    def test_read_tools(self):
        err, ctx = self._call("get_context")
        self.assertFalse(err)
        self.assertEqual(ctx["user"]["login"], "mcp_tester")
        err, models = self._call("list_models")
        self.assertIn("res.partner", [m["model"] for m in models])
        err, data = self._call(
            "search_records",
            {"model": "res.partner", "domain": [["name", "=", "MCP Partner X1"]], "fields": ["name"]},
        )
        self.assertFalse(err)
        self.assertEqual(data["records"][0]["id"], self.partner.id)
        err, fields_ = self._call("get_fields", {"model": "res.partner"})
        self.assertIn("name", fields_)

    def test_allowlist_is_deny_by_default(self):
        err, msg = self._call("search_records", {"model": "res.users"})
        self.assertTrue(err)
        self.assertIn("not exposed", msg)
        # Exposed for read only: writes are refused.
        err, msg = self._call("create_record", {"model": "res.partner", "values": {"name": "Nope"}})
        self.assertTrue(err)
        self.assertIn("not allowed", msg)
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Nope")]))

    def test_write_tools_and_log(self):
        self.rule.write({"allow_create": True, "allow_write": True})
        err, created = self._call("create_record", {"model": "res.partner", "values": {"name": "MCP Made"}})
        self.assertFalse(err)
        err, _ = self._call(
            "update_record", {"model": "res.partner", "id": created["id"], "values": {"name": "MCP Renamed"}}
        )
        self.assertFalse(err)
        self.assertEqual(self.env["res.partner"].browse(created["id"]).name, "MCP Renamed")
        logs = self.env["mna.mcp.log"].search([("user_id", "=", self.user.id)])
        self.assertEqual(set(logs.mapped("tool")), {"create_record", "update_record"})
        self.assertTrue(all(logs.mapped("success")))

    def test_user_rights_apply(self):
        # Exposing a model does not bypass the user's own access rights.
        self.env["mna.mcp.model"].create(
            {"model_id": self.env.ref("base.model_ir_config_parameter").id}
        )
        err, msg = self._call("search_records", {"model": "ir.config_parameter"})
        self.assertTrue(err)
