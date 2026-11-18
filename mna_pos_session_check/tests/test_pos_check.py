from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosSessionCheck(TestPoSCommon):
    """The checks must be right in both directions.

    A report that cries wolf is worse than no report, so every check is
    tested for the clean case as well as the dirty one: silence when
    there is nothing wrong matters as much as noise when there is.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.product = cls.create_product("Coffee", cls.categ_basic, 3.0, 1.0)

    def _check(self, **values):
        check = self.env["mna.pos.check"].create(values)
        check._run()
        return check

    def _result(self, check, name_fragment):
        line = check.line_ids.filtered(lambda l: name_fragment.lower() in l.name.lower())
        self.assertTrue(line, "no check named like %r" % name_fragment)
        return line[0]

    def _closed_session(self, difference=0.0):
        """Close the way a cashier does: count the cash, then close.

        Closing without entering a counted amount leaves the whole
        takings as a difference, which would make every session in these
        tests look short and prove nothing.
        """
        self.open_new_session()
        session = self.pos_session
        order = self.create_ui_order_data([(self.product, 2)])
        self.env["pos.order"].sync_from_ui([order])

        cash_method = session.payment_method_ids.filtered("is_cash_count")[:1]
        counted = sum(
            session.mapped("order_ids.payment_ids")
            .filtered(lambda p: p.payment_method_id == cash_method)
            .mapped("amount")
        )
        session.post_closing_cash_details(counted + difference)
        session.close_session_from_ui()
        return session

    # ------------------------------------------------------------------
    def test_01_clean_shop_reports_nothing(self):
        self._closed_session()
        check = self._check()
        self.assertEqual(check.problem_count, 0)
        self.assertEqual(check.warning_count, 0)
        self.assertTrue(check.line_ids, "the checks still report, they just report OK")
        self.assertTrue(all(l.status == "ok" for l in check.line_ids))

    def test_02_session_open_too_long_is_a_problem(self):
        self.open_new_session()
        self.pos_session.start_at = fields.Datetime.subtract(
            fields.Datetime.now(), days=9
        )
        check = self._check(max_open_days=2)
        line = self._result(check, "left open")
        self.assertEqual(line.status, "problem")
        self.assertEqual(line.count, 1)
        self.assertIn("9 days", line.detail)

    def test_03_a_session_open_since_this_morning_is_not_flagged(self):
        """The commonest false positive, and the reason for the threshold."""
        self.open_new_session()
        self.pos_session.start_at = fields.Datetime.subtract(
            fields.Datetime.now(), hours=6
        )
        check = self._check(max_open_days=2)
        self.assertEqual(self._result(check, "left open").status, "ok")

    def test_04_cash_difference_above_threshold_is_reported(self):
        self._closed_session(difference=-40.0)
        check = self._check(difference_threshold=5.0)
        line = self._result(check, "closing difference")
        self.assertNotEqual(line.status, "ok")
        self.assertEqual(line.count, 1)

    def test_05_difference_below_threshold_is_noise(self):
        self._closed_session(difference=-1.5)
        check = self._check(difference_threshold=5.0)
        self.assertEqual(self._result(check, "closing difference").status, "ok")

    def test_06_totals_separate_net_from_absolute(self):
        """Offsetting differences must not net out to a clean bill of health."""
        self._closed_session(difference=60.0)
        self._closed_session(difference=-60.0)
        check = self._check(difference_threshold=5.0)
        self.assertAlmostEqual(check.total_difference, 0.0)
        self.assertAlmostEqual(check.absolute_difference, 120.0)

    def test_07_repeat_differences_need_three_sessions(self):
        for _i in range(2):
            self._closed_session(difference=-30.0)
        check = self._check(difference_threshold=5.0)
        self.assertEqual(self._result(check, "following one person").status, "ok",
                         "two sessions is not yet a pattern")

        self._closed_session(difference=-30.0)
        check = self._check(difference_threshold=5.0)
        line = self._result(check, "following one person")
        self.assertEqual(line.status, "warning")
        self.assertIn("conversation", line.detail)

    def test_08_order_marked_to_invoice_without_an_invoice(self):
        session = self._closed_session()
        order = session.order_ids[0]
        order.write({"to_invoice": True})
        check = self._check()
        line = self._result(check, "Invoices never issued")
        self.assertEqual(line.status, "problem")
        self.assertEqual(line.count, 1)
        self.assertEqual(line.res_model, "pos.order")

    def test_09_draft_session_entry_is_a_problem(self):
        session = self._closed_session()
        if not session.move_id:
            self.skipTest("this session posted no journal entry")
        session.move_id.button_draft()
        check = self._check()
        self.assertEqual(self._result(check, "not posted").status, "problem")

    def test_10_hand_typed_negative_line_is_flagged(self):
        session = self._closed_session()
        line = session.order_ids[0].lines[0]
        line.qty = -1
        check = self._check()
        result = self._result(check, "Negative lines")
        self.assertEqual(result.status, "warning")
        self.assertEqual(result.count, 1)

    def test_11_a_real_refund_is_not_flagged(self):
        """A refund has negative lines by nature and must stay quiet."""
        session = self._closed_session()
        original = session.order_ids[0].lines[0]
        self.open_new_session()
        refund_order = self.env["pos.order"].create({
            "session_id": self.pos_session.id,
            "company_id": self.env.company.id,
            "amount_tax": 0, "amount_total": -3.0, "amount_paid": 0, "amount_return": 0,
            "lines": [(0, 0, {
                "product_id": self.product.id, "qty": -1,
                "price_unit": 3.0, "price_subtotal": -3.0, "price_subtotal_incl": -3.0,
                "refunded_orderline_id": original.id,
            })],
        })
        # The refund has to be paid out, or the session's own entry does
        # not balance and the close is refused, which is correct of Odoo.
        cash_method = self.pos_session.payment_method_ids.filtered("is_cash_count")[:1]
        refund_order.add_payment({
            "amount": -3.0,
            "payment_method_id": cash_method.id,
            "pos_order_id": refund_order.id,
        })
        refund_order.action_pos_order_paid()
        self.pos_session.post_closing_cash_details(-3.0)
        self.pos_session.close_session_from_ui()
        check = self._check()
        flagged = self._result(check, "Negative lines")
        self.assertEqual(flagged.status, "ok", "a linked refund is not a hand typed negative")
        self.assertTrue(refund_order.exists())

    def test_12_scope_restricts_to_the_chosen_shop(self):
        self._closed_session(difference=-50.0)
        other = self.env["pos.config"].create({"name": "Second Shop"})
        check = self._check(config_ids=[(6, 0, other.ids)], difference_threshold=5.0)
        self.assertEqual(check.session_count, 0)
        self.assertEqual(self._result(check, "closing difference").status, "ok")

    def test_13_a_cashier_cannot_run_the_check(self):
        cashier = self.env["res.users"].create({
            "name": "Till User", "login": "mna_pos_till_user",
            self._groups_field(): [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("point_of_sale.group_pos_user").id,
            ])],
        })
        check = self.env["mna.pos.check"].create({})
        with self.assertRaises(AccessError):
            check.with_user(cashier)._run()

    def _groups_field(self):
        return "group_ids" if "group_ids" in self.env["res.users"]._fields else "groups_id"
