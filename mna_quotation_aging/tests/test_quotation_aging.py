# Part of the Najjarine Tech Odoo modules. See LICENSE file for full
# copyright and licensing details.
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestQuotationAging(TransactionCase):
    """The bucket boundaries and the win rate are the two things a
    manager will check by hand, so both are asserted against figures
    worked out in the test rather than read back off the report.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create({"name": "Aging Customer"})
        cls.seller_a = cls.env["res.users"].create({
            "name": "Aging Seller A",
            "login": "mna_aging_a",
            "email": "a@example.com",
        })
        cls.seller_b = cls.env["res.users"].create({
            "name": "Aging Seller B",
            "login": "mna_aging_b",
            "email": "b@example.com",
        })
        cls.product = cls.env["product.product"].create({
            "name": "Aging Product",
            "type": "consu",
            "list_price": 100.0,
            "standard_price": 60.0,
        })

    # ------------------------------------------------------------------
    def _quote(self, age_days=0, user=None, state="draft", amount=100.0,
               validity=None, qty=1.0):
        """A quotation dated age_days ago, left open unless asked."""
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "user_id": (user or self.seller_a).id if user is not False
            else False,
            "company_id": self.company.id,
            "order_line": [(0, 0, {
                "product_id": self.product.id,
                "product_uom_qty": qty,
                "price_unit": amount,
            })],
        })
        if validity is not None:
            order.validity_date = validity
        if state == "sale":
            order.action_confirm()
        elif state == "cancel":
            order.action_cancel()
        elif state == "sent":
            order.state = "sent"
        # Set the date last: confirming or cancelling can touch it, and
        # the age the report measures has to be the one the test meant.
        order.date_order = fields.Datetime.now() - timedelta(days=age_days)
        return order

    def _wizard(self, **vals):
        base = {
            "date_from": fields.Date.context_today(self.env.user) -
            timedelta(days=365),
            # Ahead as well as behind: one test dates a quotation in the
            # future, and a window ending today would simply not see it.
            "date_to": fields.Date.context_today(self.env.user) +
            timedelta(days=30),
            "company_id": self.company.id,
        }
        base.update(vals)
        return self.env["mna.quotation.aging"].create(base)

    def _row(self, wizard, user):
        return wizard.line_ids.filtered(
            lambda line: line.salesperson_id == user)

    # ------------------------------------------------------------------
    # buckets
    # ------------------------------------------------------------------
    def test_each_bucket_catches_its_own_range(self):
        # One quotation in each bucket: 3, 10, 20, 45 and 200 days old.
        for age in (3, 10, 20, 45, 200):
            self._quote(age_days=age)
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.open_count, 5)
        self.assertEqual(row.b_0_7, 1)
        self.assertEqual(row.b_8_14, 1)
        self.assertEqual(row.b_15_30, 1)
        self.assertEqual(row.b_31_60, 1)
        self.assertEqual(row.b_60_plus, 1)
        self.assertEqual(row.oldest_days, 200)

    def test_the_bucket_boundaries_sit_where_the_labels_say(self):
        """7 belongs to 0-7 and 8 to 8-14, not the other way round."""
        wizard = self._wizard()
        self.assertEqual(wizard._bucket_for(0), "b_0_7")
        self.assertEqual(wizard._bucket_for(7), "b_0_7")
        self.assertEqual(wizard._bucket_for(8), "b_8_14")
        self.assertEqual(wizard._bucket_for(14), "b_8_14")
        self.assertEqual(wizard._bucket_for(15), "b_15_30")
        self.assertEqual(wizard._bucket_for(30), "b_15_30")
        self.assertEqual(wizard._bucket_for(31), "b_31_60")
        self.assertEqual(wizard._bucket_for(60), "b_31_60")
        self.assertEqual(wizard._bucket_for(61), "b_60_plus")
        self.assertEqual(wizard._bucket_for(5000), "b_60_plus")

    def test_a_quotation_dated_ahead_lands_in_the_youngest_bucket(self):
        # Negative age, which is still a real open quotation and must
        # not vanish from the counts.
        self._quote(age_days=-3)
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.open_count, 1)
        self.assertEqual(row.b_0_7, 1)

    def test_bucket_counts_add_up_to_the_open_count(self):
        for age in (1, 2, 9, 16, 40, 90, 300):
            self._quote(age_days=age)
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        buckets = (row.b_0_7 + row.b_8_14 + row.b_15_30 + row.b_31_60 +
                   row.b_60_plus)
        self.assertEqual(buckets, 7)
        self.assertEqual(row.open_count, 7)

    # ------------------------------------------------------------------
    # what counts as open, won and lost
    # ------------------------------------------------------------------
    def test_sent_counts_as_open_and_confirmed_does_not(self):
        self._quote(age_days=5, state="draft")
        self._quote(age_days=5, state="sent")
        self._quote(age_days=5, state="sale")
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.open_count, 2)
        self.assertEqual(row.won_count, 1)

    def test_win_rate_is_won_over_what_was_decided(self):
        # 3 won and 1 lost is 3 of 4 decided, which is 75 percent. The
        # two still open must not drag it down.
        for _unused in range(3):
            self._quote(state="sale")
        self._quote(state="cancel")
        self._quote(state="draft")
        self._quote(state="draft")
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.won_count, 3)
        self.assertEqual(row.lost_count, 1)
        self.assertAlmostEqual(row.win_rate, 75.0, places=2)
        self.assertAlmostEqual(wizard.total_win_rate, 75.0, places=2)

    def test_win_rate_is_zero_rather_than_a_crash_when_nothing_decided(self):
        self._quote(state="draft")
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.won_count, 0)
        self.assertEqual(row.lost_count, 0)
        self.assertAlmostEqual(row.win_rate, 0.0, places=2)

    # ------------------------------------------------------------------
    # expiry and next step
    # ------------------------------------------------------------------
    def test_expired_counts_only_open_quotations_past_their_date(self):
        today = fields.Date.context_today(self.env.user)
        self._quote(age_days=30, validity=today - timedelta(days=5))
        self._quote(age_days=30, validity=today + timedelta(days=5))
        self._quote(age_days=30, validity=False)
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.open_count, 3)
        self.assertEqual(row.expired_count, 1)

    def test_a_confirmed_order_past_its_validity_is_not_expired(self):
        # It was accepted, so the expiry date stopped mattering.
        today = fields.Date.context_today(self.env.user)
        self._quote(age_days=30, state="sale",
                    validity=today - timedelta(days=5))
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.expired_count, 0)
        self.assertEqual(row.won_count, 1)

    def test_a_scheduled_next_step_clears_the_no_next_step_count(self):
        with_step = self._quote(age_days=10)
        without = self._quote(age_days=10)
        self.env["mail.activity"].create({
            "res_model_id": self.env["ir.model"]._get_id("sale.order"),
            "res_id": with_step.id,
            "activity_type_id": self.env.ref(
                "mail.mail_activity_data_call").id,
            "user_id": self.env.user.id,
            "summary": "Chase this one",
        })
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertEqual(row.open_count, 2)
        self.assertEqual(row.no_activity_count, 1)
        self.assertTrue(without.id)

    # ------------------------------------------------------------------
    # value, currency and grouping
    # ------------------------------------------------------------------
    def test_open_value_adds_up_the_open_ones_only(self):
        # Two open at 250 each is 500. The confirmed one at 1000 is won,
        # not open, and must not be in the open value.
        self._quote(amount=250.0, qty=1.0)
        self._quote(amount=250.0, qty=1.0)
        self._quote(amount=1000.0, qty=1.0, state="sale")
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        self.assertAlmostEqual(row.open_amount, 500.0, places=2)
        self.assertAlmostEqual(wizard.total_open_amount, 500.0, places=2)

    def test_a_foreign_currency_order_is_converted(self):
        """A pipeline figure that adds currencies without converting is
        meaningless, so the conversion is asserted at a known rate."""
        company_currency = self.company.currency_id
        # A database installed without demo data has only the company
        # currency active, so the second one is taken from the inactive
        # ones and switched on.
        other = self.env["res.currency"].with_context(
            active_test=False).search(
            [("id", "!=", company_currency.id)], limit=1)
        self.assertTrue(other, "the database needs a second currency")
        other.active = True
        order_date = fields.Date.context_today(self.env.user) - timedelta(
            days=10)
        self.env["res.currency.rate"].search([
            ("currency_id", "=", other.id),
            ("company_id", "in", (self.company.id, False)),
        ]).unlink()
        self.env["res.currency.rate"].create({
            "currency_id": other.id,
            "company_id": self.company.id,
            "name": order_date,
            # Two of the other currency to one of ours.
            "rate": 2.0,
        })
        order = self._quote(age_days=10, amount=400.0, qty=1.0)
        order.currency_id = other
        wizard = self._wizard()
        wizard.action_run()
        row = self._row(wizard, self.seller_a)
        # 400 at two to one is 200 in the company's currency.
        self.assertAlmostEqual(row.open_amount, 200.0, places=2)

    def test_each_salesperson_gets_their_own_row(self):
        self._quote(user=self.seller_a)
        self._quote(user=self.seller_a)
        self._quote(user=self.seller_b)
        wizard = self._wizard()
        wizard.action_run()
        self.assertEqual(self._row(wizard, self.seller_a).open_count, 2)
        self.assertEqual(self._row(wizard, self.seller_b).open_count, 1)

    def test_quotations_with_no_salesperson_get_a_row_of_their_own(self):
        """An unowned quotation is the one most likely to rot, so it has
        to appear somewhere rather than be dropped."""
        self._quote(user=False)
        wizard = self._wizard()
        wizard.action_run()
        orphan = wizard.line_ids.filtered(
            lambda line: not line.salesperson_id)
        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan.open_count, 1)

    def test_my_quotations_only_narrows_to_the_current_user(self):
        self._quote(user=self.env.user)
        self._quote(user=self.seller_a)
        wizard = self._wizard(only_my_team=True)
        wizard.action_run()
        self.assertEqual(wizard.total_open, 1)
        self.assertEqual(
            self._row(wizard, self.env.user).open_count, 1)
        self.assertFalse(self._row(wizard, self.seller_a))

    # ------------------------------------------------------------------
    # housekeeping
    # ------------------------------------------------------------------
    def test_a_period_with_nothing_in_it_says_so(self):
        today = fields.Date.context_today(self.env.user)
        wizard = self._wizard(date_from=today - timedelta(days=4000),
                              date_to=today - timedelta(days=3990))
        wizard.action_run()
        self.assertTrue(wizard.has_run)
        self.assertFalse(wizard.line_ids)
        self.assertEqual(wizard.total_open, 0)
        self.assertIn("No quotations", wizard.note)

    def test_outside_the_period_is_outside_the_report(self):
        self._quote(age_days=400)
        today = fields.Date.context_today(self.env.user)
        wizard = self._wizard(date_from=today - timedelta(days=30),
                              date_to=today)
        wizard.action_run()
        self.assertEqual(wizard.total_open, 0)

    def test_running_twice_does_not_double_the_rows(self):
        self._quote()
        wizard = self._wizard()
        wizard.action_run()
        first = len(wizard.line_ids)
        wizard.action_run()
        self.assertEqual(len(wizard.line_ids), first)
        self.assertEqual(first, 1)

    def test_a_backwards_date_range_is_refused(self):
        today = fields.Date.context_today(self.env.user)
        wizard = self._wizard(date_from=today,
                              date_to=today - timedelta(days=1))
        with self.assertRaises(UserError):
            wizard.action_run()

    def test_a_row_opens_the_quotations_behind_it(self):
        self._quote(user=self.seller_a)
        wizard = self._wizard()
        wizard.action_run()
        action = self._row(wizard, self.seller_a).action_open_quotations()
        self.assertEqual(action["res_model"], "sale.order")
        found = self.env["sale.order"].search(action["domain"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found.user_id, self.seller_a)
