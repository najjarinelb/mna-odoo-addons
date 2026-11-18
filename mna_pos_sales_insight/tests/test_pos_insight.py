from odoo import fields
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosInsight(TestPoSCommon):
    """The view has to agree with the orders it is built from."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        # Sold at 10, costing 4, so the margin is 6 a unit and nothing in
        # the assertions below has to be recomputed to be read.
        cls.product = cls.create_product("Latte", cls.categ_basic, 10.0, 4.0)
        cls.insight = cls.env["mna.pos.insight"]

    def _sell(self, qty=1, discount=0.0):
        self.open_new_session()
        session = self.pos_session
        order = self.create_ui_order_data([(self.product, qty, discount)]
                                          if discount else [(self.product, qty)])
        self.env["pos.order"].sync_from_ui([order])
        cash = session.payment_method_ids.filtered("is_cash_count")[:1]
        counted = sum(session.mapped("order_ids.payment_ids")
                      .filtered(lambda p: p.payment_method_id == cash).mapped("amount"))
        session.post_closing_cash_details(counted)
        session.close_session_from_ui()
        return session

    def _rows(self):
        return self.insight.search([("product_id", "=", self.product.id)])

    def test_01_a_sale_appears_with_its_margin(self):
        self._sell(qty=3)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row.qty, 3.0)
        self.assertAlmostEqual(row.revenue, 30.0)
        self.assertAlmostEqual(row.cost, 12.0)
        self.assertAlmostEqual(row.margin, 18.0)
        self.assertAlmostEqual(row.margin_percent, 60.0)
        self.assertTrue(row.has_cost)

    def test_02_margin_agrees_with_the_order_itself(self):
        """The view must not invent a number the order disagrees with."""
        session = self._sell(qty=2)
        order = session.order_ids[0]
        row = self._rows()[0]
        self.assertAlmostEqual(row.margin, order.lines[0].margin, places=2)

    def test_03_a_line_without_a_cost_is_marked(self):
        free = self.create_product("Tap Water", self.categ_basic, 2.0)
        self.open_new_session()
        session = self.pos_session
        self.env["pos.order"].sync_from_ui(
            [self.create_ui_order_data([(free, 1)])]
        )
        cash = session.payment_method_ids.filtered("is_cash_count")[:1]
        counted = sum(session.mapped("order_ids.payment_ids")
                      .filtered(lambda p: p.payment_method_id == cash).mapped("amount"))
        session.post_closing_cash_details(counted)
        session.close_session_from_ui()

        row = self.insight.search([("product_id", "=", free.id)])
        self.assertEqual(len(row), 1)
        self.assertFalse(row.has_cost, "a line with no cost must say so")
        self.assertAlmostEqual(row.margin, row.revenue,
                               msg="margin equals revenue, which is why it is flagged")

    def test_04_hour_of_day_uses_the_company_timezone(self):
        """A UTC hour would put a Beirut evening peak in the afternoon."""
        self._sell()
        row = self._rows()[0]
        order = row.order_id

        self.env.company.partner_id.tz = "Asia/Beirut"
        self.env.invalidate_all()
        beirut = self.insight.browse(row.id).hour_of_day

        self.env.company.partner_id.tz = "UTC"
        self.env.invalidate_all()
        utc = self.insight.browse(row.id).hour_of_day

        offset = (beirut - utc) % 24
        self.assertIn(offset, (2, 3), "Beirut is UTC+2 or UTC+3 depending on the season")
        self.assertEqual(utc, order.date_order.hour)

    def test_05_discount_is_reported_in_money(self):
        # Written through pos.order directly rather than the UI helper,
        # which passes a discount through without applying it to the
        # subtotal, so the order would not balance.
        self.open_new_session()
        session = self.pos_session
        order = self.env["pos.order"].create({
            "session_id": session.id,
            "company_id": self.env.company.id,
            "amount_tax": 0.0, "amount_total": 18.0,
            "amount_paid": 0.0, "amount_return": 0.0,
            "lines": [(0, 0, {
                "product_id": self.product.id,
                "qty": 2, "discount": 10.0, "price_unit": 10.0,
                "price_subtotal": 18.0, "price_subtotal_incl": 18.0,
                "total_cost": 8.0,
            })],
        })
        cash = session.payment_method_ids.filtered("is_cash_count")[:1]
        order.add_payment({"amount": 18.0, "payment_method_id": cash.id,
                           "pos_order_id": order.id})
        order.action_pos_order_paid()
        session.post_closing_cash_details(18.0)
        session.close_session_from_ui()

        row = self._rows()[0]
        self.assertAlmostEqual(row.discount_percent, 10.0)
        self.assertAlmostEqual(row.discount_amount, 2.0,
                               msg="10% of two units at 10 is 2.00")
        self.assertAlmostEqual(row.revenue, 18.0)

    def test_06_an_unpaid_order_is_not_revenue_yet(self):
        """Only settled orders reach the view."""
        self.open_new_session()
        draft = self.env["pos.order"].create({
            "session_id": self.pos_session.id,
            "company_id": self.env.company.id,
            "amount_tax": 0.0, "amount_total": 10.0,
            "amount_paid": 0.0, "amount_return": 0.0,
            "lines": [(0, 0, {
                "product_id": self.product.id, "qty": 1,
                "price_unit": 10.0, "price_subtotal": 10.0,
                "price_subtotal_incl": 10.0, "total_cost": 4.0,
            })],
        })
        self.assertEqual(draft.state, "draft")
        self.assertFalse(
            self.insight.search([("order_id", "=", draft.id)]),
            "a draft order is not revenue yet",
        )

    def test_07_grouping_by_cashier_totals_correctly(self):
        self._sell(qty=1)
        self._sell(qty=2)
        groups = self.insight._read_group(
            [("product_id", "=", self.product.id)],
            groupby=["user_id"], aggregates=["revenue:sum", "margin:sum"],
        )
        self.assertEqual(len(groups), 1)
        _user, revenue, margin = groups[0]
        self.assertAlmostEqual(revenue, 30.0)
        self.assertAlmostEqual(margin, 18.0)

    def test_08_a_cashier_cannot_read_the_report(self):
        from odoo.exceptions import AccessError
        cashier = self.env["res.users"].create({
            "name": "Till Only", "login": "mna_insight_till",
            ("group_ids" if "group_ids" in self.env["res.users"]._fields
             else "groups_id"): [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("point_of_sale.group_pos_user").id])],
        })
        with self.assertRaises(AccessError):
            self.insight.with_user(cashier).search([])
