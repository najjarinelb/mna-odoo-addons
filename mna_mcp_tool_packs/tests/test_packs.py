from datetime import date, timedelta

from odoo.tests import HttpCase, tagged

from odoo.addons.mna_mcp_server.controllers.main import EXTRA_TOOLS


@tagged("post_install", "-at_install")
class TestMcpToolPacks(HttpCase):
    """Drive the tools through the real /mcp endpoint.

    Calling the controller methods directly would skip authentication, the
    allowlist and the JSON-RPC envelope, which is most of what can break.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "MCP Pack Tester",
                "login": "mcp_pack_tester",
                "groups_id": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref("account.group_account_invoice").id),
                    (4, cls.env.ref("sales_team.group_sale_salesman").id),
                    (4, cls.env.ref("stock.group_stock_user").id),
                    (4, cls.env.ref("purchase.group_purchase_user").id),
                ],
            }
        )
        _record, cls.secret = cls.env["mna.mcp.key"]._generate("pack tests", cls.user)

    def _expose(self, *models):
        for name in models:
            existing = self.env["mna.mcp.model"].with_context(
                active_test=False
            ).search([("model", "=", name)])
            if existing:
                existing.write({"allow_read": True, "active": True})
                continue
            ir_model = self.env["ir.model"]._get(name)
            self.assertTrue(ir_model, "Model %s is not installed" % name)
            self.env["mna.mcp.model"].create(
                {"model_id": ir_model.id, "allow_read": True}
            )
        self.env.flush_all()

    def _rpc(self, method, params=None, tool_args=None):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        response = self.url_open(
            "/mcp",
            data=__import__("json").dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % self.secret,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _call(self, name, arguments=None):
        body = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        result = body["result"]
        text = result["content"][0]["text"]
        return result.get("isError", False), text

    def _ok(self, name, arguments=None):
        is_error, text = self._call(name, arguments)
        self.assertFalse(is_error, "%s returned an error: %s" % (name, text))
        return __import__("json").loads(text)

    # ------------------------------------------------------------------

    def test_01_packs_are_registered(self):
        names = {tool["name"] for tool in EXTRA_TOOLS}
        self.assertIn("sales_summary", names)
        self.assertIn("aged_receivable", names)
        self.assertIn("stock_on_hand", names)
        self.assertIn("purchase_summary", names)

    def test_02_tools_list_includes_packs_and_core(self):
        tools = self._rpc("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertIn("search_records", names, "core tools must survive the extension")
        self.assertIn("sales_summary", names)
        for tool in tools:
            self.assertNotIn("_available", tool, "internal keys must not reach the client")
            self.assertIn("inputSchema", tool)

    def test_03_allowlist_is_enforced(self):
        """A pack tool must stay shut until its model is exposed."""
        self.env["mna.mcp.model"].search([("model", "=", "sale.order")]).write(
            {"allow_read": False}
        )
        self.env.flush_all()
        is_error, text = self._call("sales_summary", {})
        self.assertTrue(is_error)
        self.assertIn("sale.order", text)

    def test_04_sales_summary_matches_a_hand_count(self):
        self._expose("sale.order", "sale.order.line")
        today = date.today()
        partner = self.env["res.partner"].create({"name": "Pack Customer"})
        product = self.env["product.product"].create(
            {"name": "Pack Widget", "list_price": 100.0, "taxes_id": [(5, 0, 0)]}
        )
        orders = self.env["sale.order"]
        for quantity in (2, 3):
            order = self.env["sale.order"].create(
                {
                    "partner_id": partner.id,
                    "user_id": self.user.id,
                    "date_order": today.isoformat() + " 10:00:00",
                    "order_line": [
                        (0, 0, {"product_id": product.id, "product_uom_qty": quantity,
                                "price_unit": 100.0})
                    ],
                }
            )
            order.action_confirm()
            orders |= order
        self.env.flush_all()

        expected = sum(orders.mapped("amount_total"))

        data = self._ok("sales_summary", {"period": "today"})
        self.assertAlmostEqual(data["total"], round(expected, 2), places=2)

        by_person = self._ok("sales_summary", {"period": "today", "group_by": "salesperson"})
        mine = [g for g in by_person["groups"] if g["salesperson"]["id"] == self.user.id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["orders"], 2)
        self.assertAlmostEqual(mine[0]["revenue"], round(expected, 2), places=2)

        by_product = self._ok("sales_summary", {"period": "today", "group_by": "product"})
        rows = [g for g in by_product["groups"] if g["product"]["id"] == product.id]
        self.assertEqual(rows[0]["quantity"], 5.0)
        self.assertEqual(rows[0]["revenue"], 500.0)
        self.assertIsNone(
            by_product["total"], "a line level total would not reconcile with order totals"
        )

    def test_05_aged_receivable_buckets_by_due_date(self):
        self._expose("account.move", "account.move.line")
        today = date.today()
        partner = self.env["res.partner"].create({"name": "Pack Debtor"})
        product = self.env["product.product"].create({"name": "Pack Service"})

        for days, amount in ((5, 100.0), (45, 200.0), (120, 400.0)):
            invoice = self.env["account.move"].create(
                {
                    "move_type": "out_invoice",
                    "partner_id": partner.id,
                    "invoice_date": today - timedelta(days=days),
                    "invoice_date_due": today - timedelta(days=days),
                    "invoice_line_ids": [
                        (0, 0, {"product_id": product.id, "quantity": 1,
                                "price_unit": amount, "tax_ids": [(5, 0, 0)]})
                    ],
                }
            )
            invoice.action_post()
        self.env.flush_all()

        data = self._ok("aged_receivable", {"partner_id": partner.id})
        rows = [r for r in data["partners"] if r["partner_id"] == partner.id]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row["1_30"], 100.0, places=2)
        self.assertAlmostEqual(row["31_60"], 200.0, places=2)
        self.assertAlmostEqual(row["over_90"], 400.0, places=2)
        self.assertAlmostEqual(row["total"], 700.0, places=2)

    def test_06_unpaid_invoices_reports_residual_not_total(self):
        """A part paid invoice must show what is left, not what it was."""
        self._expose("account.move", "account.move.line")
        today = date.today()
        partner = self.env["res.partner"].create({"name": "Pack Part Payer"})
        product = self.env["product.product"].create({"name": "Pack Item"})
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "invoice_date": today,
                "invoice_date_due": today,
                "invoice_line_ids": [
                    (0, 0, {"product_id": product.id, "quantity": 1,
                            "price_unit": 1000.0, "tax_ids": [(5, 0, 0)]})
                ],
            }
        )
        invoice.action_post()

        payment = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create({"amount": 400.0, "payment_date": today})
        payment._create_payments()
        self.env.flush_all()

        data = self._ok("unpaid_invoices", {"partner_id": partner.id})
        rows = [r for r in data["invoices"] if r["invoice"] == invoice.name]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["amount_total"], 1000.0, places=2)
        self.assertAlmostEqual(rows[0]["amount_due"], 600.0, places=2)
        self.assertEqual(rows[0]["payment_state"], "partial")

    def test_07_revenue_by_period_nets_credit_notes(self):
        self._expose("account.move")
        today = date.today()
        partner = self.env["res.partner"].create({"name": "Pack Revenue"})
        product = self.env["product.product"].create({"name": "Pack Line"})

        def post(move_type, amount):
            move = self.env["account.move"].create(
                {
                    "move_type": move_type,
                    "partner_id": partner.id,
                    "invoice_date": today,
                    "invoice_line_ids": [
                        (0, 0, {"product_id": product.id, "quantity": 1,
                                "price_unit": amount, "tax_ids": [(5, 0, 0)]})
                    ],
                }
            )
            move.action_post()
            return move

        before = self._ok("revenue_by_period", {"period": "this_month"})["net_total"]
        post("out_invoice", 1000.0)
        post("out_refund", 250.0)
        self.env.flush_all()
        after = self._ok("revenue_by_period", {"period": "this_month"})

        self.assertAlmostEqual(after["net_total"] - before, 750.0, places=2)
        label = today.strftime("%Y-%m")
        row = [p for p in after["periods"] if p["period"] == label]
        self.assertTrue(row, "the current month must appear as %s" % label)

    def test_08_stock_on_hand_sums_internal_locations(self):
        self._expose("stock.quant")
        product = self.env["product.product"].create(
            {"name": "Pack Stocked", "is_storable": True}
        )
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": product.id,
                "location_id": warehouse.lot_stock_id.id,
                "inventory_quantity": 17.0,
            }
        ).action_apply_inventory()
        self.env.flush_all()

        data = self._ok("stock_on_hand", {"product_id": product.id})
        rows = [r for r in data["products"] if r["product"]["id"] == product.id]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["on_hand"], 17.0, places=3)
        self.assertAlmostEqual(rows[0]["available"], 17.0, places=3)

    def test_09_low_stock_flags_a_product_under_its_minimum(self):
        self._expose("stock.quant")
        product = self.env["product.product"].create(
            {"name": "Pack Reordered", "is_storable": True}
        )
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": product.id,
                "location_id": warehouse.lot_stock_id.id,
                "product_min_qty": 10.0,
                "product_max_qty": 50.0,
            }
        )
        self.env.flush_all()

        data = self._ok("low_stock", {"limit": 100})
        rows = [r for r in data["products"] if r["product"]["id"] == product.id]
        self.assertEqual(len(rows), 1, "a product with no stock and a minimum of 10 is short")
        self.assertAlmostEqual(rows[0]["shortfall"], 10.0, places=3)

    def test_10_purchase_summary_groups_by_vendor(self):
        self._expose("purchase.order", "purchase.order.line")
        vendor = self.env["res.partner"].create({"name": "Pack Vendor"})
        product = self.env["product.product"].create({"name": "Pack Supply"})
        order = self.env["purchase.order"].create(
            {
                "partner_id": vendor.id,
                "order_line": [
                    (0, 0, {
                        "product_id": product.id,
                        "name": product.name,
                        "product_qty": 4,
                        "price_unit": 25.0,
                        "date_planned": date.today().isoformat() + " 10:00:00",
                        "taxes_id": [(5, 0, 0)],
                    })
                ],
            }
        )
        order.button_confirm()
        self.env.flush_all()

        data = self._ok("purchase_summary", {"period": "today", "group_by": "vendor"})
        rows = [g for g in data["groups"] if g["vendor"]["id"] == vendor.id]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["spend"], 100.0, places=2)

    def test_11_bad_arguments_are_refused_clearly(self):
        self._expose("sale.order")
        for arguments, fragment in (
            ({"period": "last_century"}, "period"),
            ({"date_from": "not-a-date"}, "date_from"),
            ({"date_from": "2026-05-01", "date_to": "2026-01-01"}, "after"),
            ({"group_by": "colour"}, "group_by"),
            ({"limit": -3}, "limit"),
        ):
            is_error, text = self._call("sales_summary", arguments)
            self.assertTrue(is_error, "%s should have been refused" % arguments)
            self.assertIn(fragment, text)

    def test_12_pack_calls_are_audited(self):
        self._expose("sale.order")
        before = self.env["mna.mcp.log"].search_count([("tool", "=", "sales_summary")])
        self._ok("sales_summary", {"period": "today"})
        after = self.env["mna.mcp.log"].search_count([("tool", "=", "sales_summary")])
        self.assertEqual(after, before + 1, "pack tools must land in the audit log too")
