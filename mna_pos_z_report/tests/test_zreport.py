from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosZReport(TestPoSCommon):
    """A Z report is a legal document in several markets.

    So the tests cover not only that the figures add up but that the
    document behaves like a record: numbered once, never edited, never
    deleted.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.product = cls.create_product("Tea", cls.categ_basic, 5.0, 2.0)
        cls.report_model = cls.env["mna.pos.zreport"]

    def _sell(self, qty=1):
        order = self.create_ui_order_data([(self.product, qty)])
        self.env["pos.order"].sync_from_ui([order])

    def _close(self, offset=0.0):
        session = self.pos_session
        cash = session.payment_method_ids.filtered("is_cash_count")[:1]
        counted = sum(
            session.mapped("order_ids.payment_ids")
            .filtered(lambda p: p.payment_method_id == cash).mapped("amount")
        )
        session.post_closing_cash_details(counted + offset)
        session.close_session_from_ui()
        return session

    def _traded_session(self, orders=3, qty=2, offset=0.0):
        self.open_new_session()
        for _i in range(orders):
            self._sell(qty)
        return self._close(offset)

    # ------------------------------------------------------------------
    def test_01_z_report_totals_match_the_session(self):
        session = self._traded_session(orders=3, qty=2)
        report = self.report_model._build(session, "z")

        self.assertEqual(report.order_count, 3)
        self.assertAlmostEqual(report.item_count, 6.0)
        self.assertAlmostEqual(report.net_sales, 30.0, msg="6 items at 5.00")
        self.assertAlmostEqual(
            report.total_sales, sum(session.order_ids.mapped("amount_total"))
        )
        self.assertAlmostEqual(report.average_basket, 10.0)

    def test_02_payment_methods_include_the_unused_ones(self):
        """A method missing from a Z report reads as an omission."""
        session = self._traded_session()
        report = self.report_model._build(session, "z")

        names = report.payment_line_ids.mapped("name")
        for method in session.payment_method_ids:
            self.assertIn(method.display_name, names)
        used = report.payment_line_ids.filtered(lambda l: l.amount)
        self.assertTrue(used, "something was taken")
        self.assertAlmostEqual(
            sum(report.payment_line_ids.mapped("amount")), report.total_sales
        )

    def test_03_cash_reconciliation_adds_up(self):
        session = self._traded_session(orders=2, qty=1)
        report = self.report_model._build(session, "z")

        self.assertAlmostEqual(
            report.expected_cash,
            report.opening_float + report.cash_sales + report.cash_in + report.cash_out,
        )
        self.assertAlmostEqual(report.cash_difference, 0.0,
                               msg="the till was counted correctly")

    def test_04_a_short_till_shows_the_difference(self):
        session = self._traded_session(orders=2, qty=1, offset=-7.5)
        report = self.report_model._build(session, "z")
        self.assertAlmostEqual(report.cash_difference, -7.5)
        self.assertAlmostEqual(
            report.cash_difference, session.cash_register_difference,
            msg="the report must agree with the session screen",
        )
        self.assertAlmostEqual(
            report.expected_cash,
            report.opening_float + report.cash_sales + report.cash_in + report.cash_out,
            msg="the cash block has to add up even when the till was short",
        )

    def test_05_a_z_report_cannot_be_taken_twice(self):
        session = self._traded_session()
        first = self.report_model._build(session, "z")
        self.assertTrue(first.name.startswith("Z/"))
        with self.assertRaises(UserError):
            self.report_model._build(session, "z")

    def test_06_a_z_report_cannot_be_edited_or_deleted(self):
        session = self._traded_session()
        report = self.report_model._build(session, "z")
        with self.assertRaises(UserError):
            report.write({"total_sales": 1.0})
        with self.assertRaises(UserError):
            report.unlink()

    def test_07_a_note_can_still_be_added(self):
        session = self._traded_session()
        report = self.report_model._build(session, "z")
        report.write({"note": "Power cut at 16:00, till restarted."})
        self.assertIn("Power cut", report.note)

    def test_08_a_z_report_needs_a_closed_session(self):
        self.open_new_session()
        self._sell()
        with self.assertRaises(UserError):
            self.report_model._build(self.pos_session, "z")
        self._close()

    def test_09_an_x_report_works_mid_trade_and_hides_the_difference(self):
        self.open_new_session()
        self._sell(2)
        report = self.report_model._build(self.pos_session, "x")

        self.assertEqual(report.report_type, "x")
        self.assertFalse(report.name.startswith("Z/"), "an X report is not numbered")
        self.assertAlmostEqual(report.net_sales, 10.0)
        self.assertAlmostEqual(report.counted_cash, 0.0)
        self.assertAlmostEqual(
            report.cash_difference, 0.0,
            msg="nothing has been counted yet, so a difference would be noise",
        )
        self._close()

    def test_10_a_second_x_report_replaces_the_first(self):
        self.open_new_session()
        self._sell(1)
        first = self.report_model._build(self.pos_session, "x")
        first_id = first.id
        self._sell(1)
        second = self.report_model._build(self.pos_session, "x")

        self.assertFalse(self.report_model.browse(first_id).exists())
        self.assertAlmostEqual(second.net_sales, 10.0, msg="both sales counted")
        self._close()

    def test_11_an_x_report_can_be_deleted(self):
        self.open_new_session()
        self._sell()
        report = self.report_model._build(self.pos_session, "x")
        report.unlink()
        self.assertFalse(report.exists())
        self._close()

    def test_12_discount_is_the_gap_from_list_price(self):
        self.open_new_session()
        order = self.env["pos.order"].create({
            "session_id": self.pos_session.id,
            "company_id": self.env.company.id,
            "amount_tax": 0.0, "amount_total": 8.0,
            "amount_paid": 0.0, "amount_return": 0.0,
            "lines": [(0, 0, {
                "product_id": self.product.id, "qty": 2, "discount": 20.0,
                "price_unit": 5.0, "price_subtotal": 8.0, "price_subtotal_incl": 8.0,
            })],
        })
        cash = self.pos_session.payment_method_ids.filtered("is_cash_count")[:1]
        order.add_payment({"amount": 8.0, "payment_method_id": cash.id,
                           "pos_order_id": order.id})
        order.action_pos_order_paid()
        session = self._close()

        report = self.report_model._build(session, "z")
        self.assertAlmostEqual(report.gross_sales, 10.0)
        self.assertAlmostEqual(report.discount_total, 2.0)
        self.assertAlmostEqual(report.net_sales, 8.0)

    def test_13_categories_total_to_net_sales(self):
        session = self._traded_session(orders=2, qty=3)
        report = self.report_model._build(session, "z")
        self.assertAlmostEqual(
            sum(report.category_line_ids.mapped("amount")), report.net_sales
        )

    def test_14_a_cashier_cannot_take_a_report(self):
        session = self._traded_session()
        cashier = self.env["res.users"].create({
            "name": "Till Hand", "login": "mna_z_till",
            ("group_ids" if "group_ids" in self.env["res.users"]._fields
             else "groups_id"): [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("point_of_sale.group_pos_user").id])],
        })
        with self.assertRaises(UserError):
            self.report_model.with_user(cashier)._build(session, "z")

    def test_15_the_document_renders_with_its_figures_on_it(self):
        """A report nobody can print is not a report.

        Rendered as HTML rather than PDF: the PDF step needs wkhtmltopdf,
        which is a property of the server rather than of this module, and
        checking the words on the page is a better test than checking
        that the first four bytes say PDF.
        """
        session = self._traded_session(orders=2, qty=2)
        report = self.report_model._build(session, "z")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "mna_pos_z_report.report_zreport", report.ids
        )[0].decode()

        self.assertIn("Z Report", html)
        self.assertIn(report.name, html)
        self.assertIn(session.name, html)
        self.assertIn("Expected in the drawer", html)
        self.assertIn("20.00", html)  # 4 items at 5.00
