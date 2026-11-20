# Part of the Najjarine Tech Odoo modules. See LICENSE file for full
# copyright and licensing details.
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleOrderCheck(TransactionCase):
    """Every check is tested twice: once on data that should fire it, and
    once on clean data that must stay silent. A check that cries wolf is
    worse than no check, so the silent case is the one that matters.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create({"name": "Check Customer"})
        cls.salesperson = cls.env["res.users"].create({
            "name": "Check Seller",
            "login": "mna_check_seller",
            "email": "seller@example.com",
        })
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        # A widget that costs 60 and lists at 100.
        cls.widget = cls.env["product.product"].create({
            "name": "Check Widget",
            "type": "consu",
            "list_price": 100.0,
            "standard_price": 60.0,
            "invoice_policy": "delivery",
            "uom_id": cls.uom_unit.id,
        })
        # A product with no cost recorded at all.
        cls.costless = cls.env["product.product"].create({
            "name": "Check Costless",
            "type": "consu",
            "list_price": 50.0,
            "standard_price": 0.0,
            "invoice_policy": "delivery",
            "uom_id": cls.uom_unit.id,
        })
        cls.service = cls.env["product.product"].create({
            "name": "Check Service",
            "type": "service",
            "list_price": 200.0,
            "standard_price": 120.0,
            "invoice_policy": "order",
            "uom_id": cls.uom_unit.id,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _order(self, lines, confirm=True, **vals):
        order_vals = {
            "partner_id": self.partner.id,
            "user_id": self.salesperson.id,
            "company_id": self.company.id,
            "date_order": fields.Datetime.now(),
            "order_line": [(0, 0, line) for line in lines],
        }
        order_vals.update(vals)
        order = self.env["sale.order"].create(order_vals)
        if confirm:
            order.action_confirm()
        return order

    def _line(self, product=None, qty=1.0, price=100.0, discount=0.0):
        vals = {
            "product_id": (product or self.widget).id,
            "product_uom_qty": qty,
            "price_unit": price,
            "discount": discount,
        }
        return vals

    def _wizard(self, **vals):
        base = {
            # Wide on purpose: several tests back-date an order to age
            # it, and a narrow window would exclude it and make the
            # check look silent when it simply never saw the order.
            "date_from": fields.Date.context_today(self.env.user) -
            timedelta(days=365),
            "date_to": fields.Date.context_today(self.env.user) +
            timedelta(days=1),
            "company_id": self.company.id,
        }
        base.update(vals)
        return self.env["mna.sale.order.check"].create(base)

    def _run(self, wizard, order=None, check=None):
        wizard.action_run()
        lines = wizard.line_ids
        if order is not None:
            lines = lines.filtered(lambda line: line.order_id == order)
        if check is not None:
            lines = lines.filtered(lambda line: line.check == check)
        return lines

    def _only(self, **kwargs):
        """A wizard with one check on, so one rule is tested at a time."""
        off = {
            "check_below_cost": False,
            "check_discount_high": False,
            "check_zero_price": False,
            "check_delivered_not_invoiced": False,
            "check_over_invoiced": False,
            "check_expired_open": False,
            "check_no_salesperson": False,
        }
        off.update(kwargs)
        return self._wizard(**off)

    # ------------------------------------------------------------------
    # sold below cost
    # ------------------------------------------------------------------
    def test_below_cost_fires_and_states_the_loss(self):
        # 10 units at 50 against a cost of 60 loses 10 a unit, so 100.
        order = self._order([self._line(qty=10.0, price=50.0)])
        found = self._run(self._only(check_below_cost=True), order)
        self.assertEqual(len(found), 1)
        self.assertEqual(found.check, "below_cost")
        self.assertEqual(found.severity, "high")
        self.assertAlmostEqual(found.actual, 50.0, places=2)
        self.assertAlmostEqual(found.expected, 60.0, places=2)
        self.assertAlmostEqual(found.difference, -100.0, places=2)

    def test_below_cost_counts_the_discount(self):
        # 100 less 50% is 50 a unit, under the cost of 60, so 4 units
        # lose 10 each, which is 40.
        order = self._order([self._line(qty=4.0, price=100.0,
                                        discount=50.0)])
        found = self._run(self._only(check_below_cost=True), order)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found.actual, 50.0, places=2)
        self.assertAlmostEqual(found.difference, -40.0, places=2)

    def test_below_cost_silent_at_a_healthy_price(self):
        # 100 against a cost of 60 is a profit, not a finding.
        order = self._order([self._line(qty=10.0, price=100.0)])
        self.assertFalse(self._run(self._only(check_below_cost=True), order))

    def test_below_cost_silent_exactly_at_cost(self):
        # Selling at cost makes nothing and loses nothing.
        order = self._order([self._line(qty=3.0, price=60.0)])
        self.assertFalse(self._run(self._only(check_below_cost=True), order))

    def test_below_cost_silent_when_no_cost_is_recorded(self):
        # With a cost of zero there is nothing to compare against, and
        # calling it a loss would be a lie.
        order = self._order([self._line(product=self.costless, qty=5.0,
                                        price=1.0)])
        self.assertFalse(self._run(self._only(check_below_cost=True), order))

    def test_below_cost_silent_on_an_unconfirmed_quotation(self):
        # A quotation is still being negotiated.
        order = self._order([self._line(qty=10.0, price=50.0)],
                            confirm=False)
        self.assertFalse(self._run(self._only(check_below_cost=True), order))

    # ------------------------------------------------------------------
    # discount over the limit
    # ------------------------------------------------------------------
    def test_discount_over_limit_fires_with_the_amount_given_up(self):
        # 10 at 100 discounted 40% gives up 400, and 40 is 20 past a
        # limit of 20.
        order = self._order([self._line(qty=10.0, price=100.0,
                                        discount=40.0)])
        found = self._run(
            self._only(check_discount_high=True, discount_limit=20.0), order)
        self.assertEqual(len(found), 1)
        self.assertEqual(found.severity, "medium")
        self.assertAlmostEqual(found.actual, 40.0, places=2)
        self.assertAlmostEqual(found.expected, 20.0, places=2)
        self.assertAlmostEqual(found.difference, 20.0, places=2)
        self.assertIn("400.00", found.message)

    def test_discount_silent_at_exactly_the_limit(self):
        # A limit is what is allowed, so hitting it is not a breach.
        order = self._order([self._line(qty=1.0, price=100.0,
                                        discount=20.0)])
        self.assertFalse(self._run(
            self._only(check_discount_high=True, discount_limit=20.0), order))

    def test_discount_silent_with_no_discount(self):
        order = self._order([self._line(qty=1.0, price=100.0)])
        self.assertFalse(self._run(
            self._only(check_discount_high=True, discount_limit=20.0), order))

    # ------------------------------------------------------------------
    # priced at zero
    # ------------------------------------------------------------------
    def test_zero_price_fires_when_the_price_was_never_set(self):
        order = self._order([self._line(qty=2.0, price=0.0)])
        found = self._run(self._only(check_zero_price=True), order)
        self.assertEqual(len(found), 1)
        self.assertEqual(found.check, "zero_price")

    def test_zero_price_silent_on_a_deliberate_giveaway(self):
        # A full discount is how a freebie is entered on purpose.
        order = self._order([self._line(qty=2.0, price=100.0,
                                        discount=100.0)])
        self.assertFalse(self._run(self._only(check_zero_price=True), order))

    def test_zero_price_silent_on_a_priced_line(self):
        order = self._order([self._line(qty=2.0, price=100.0)])
        self.assertFalse(self._run(self._only(check_zero_price=True), order))

    # ------------------------------------------------------------------
    # delivered and not invoiced
    # ------------------------------------------------------------------
    def test_delivered_not_invoiced_fires_past_the_grace_period(self):
        order = self._order([self._line(qty=5.0, price=100.0)])
        order.order_line.qty_delivered = 5.0
        # Dated 30 days back, so well past a grace of 7.
        order.date_order = fields.Datetime.now() - timedelta(days=30)
        found = self._run(
            self._only(check_delivered_not_invoiced=True,
                       invoice_grace_days=7), order)
        self.assertEqual(len(found), 1)
        self.assertEqual(found.severity, "high")
        self.assertAlmostEqual(found.expected, 7.0, places=0)
        self.assertAlmostEqual(found.actual, 30.0, places=0)
        self.assertAlmostEqual(found.difference, 23.0, places=0)

    def test_delivered_not_invoiced_silent_inside_the_grace_period(self):
        # Delivered today, invoicing runs weekly, nothing is wrong yet.
        order = self._order([self._line(qty=5.0, price=100.0)])
        order.order_line.qty_delivered = 5.0
        found = self._run(
            self._only(check_delivered_not_invoiced=True,
                       invoice_grace_days=7), order)
        self.assertFalse(found)

    def test_delivered_not_invoiced_silent_when_nothing_shipped(self):
        # An old order with nothing delivered has nothing to invoice.
        order = self._order([self._line(qty=5.0, price=100.0)])
        order.date_order = fields.Datetime.now() - timedelta(days=30)
        self.assertFalse(self._run(
            self._only(check_delivered_not_invoiced=True,
                       invoice_grace_days=7), order))

    def test_delivered_not_invoiced_silent_once_fully_invoiced(self):
        order = self._order([self._line(qty=5.0, price=100.0)])
        order.order_line.qty_delivered = 5.0
        order.date_order = fields.Datetime.now() - timedelta(days=30)
        invoice = order._create_invoices()
        invoice.action_post()
        self.assertEqual(order.invoice_status, "invoiced")
        self.assertFalse(self._run(
            self._only(check_delivered_not_invoiced=True,
                       invoice_grace_days=7), order))

    # ------------------------------------------------------------------
    # invoiced over delivered
    # ------------------------------------------------------------------
    def test_over_invoiced_fires_on_the_gap(self):
        # Invoiced 5 against 2 delivered leaves 3 billed and unshipped.
        order = self._order([self._line(qty=5.0, price=100.0)])
        order.order_line.qty_delivered = 5.0
        invoice = order._create_invoices()
        invoice.action_post()
        order.order_line.qty_delivered = 2.0
        found = self._run(self._only(check_over_invoiced=True), order)
        self.assertEqual(len(found), 1)
        self.assertEqual(found.severity, "high")
        self.assertAlmostEqual(found.actual, 5.0, places=2)
        self.assertAlmostEqual(found.expected, 2.0, places=2)
        self.assertAlmostEqual(found.difference, 3.0, places=2)

    def test_over_invoiced_silent_when_they_match(self):
        order = self._order([self._line(qty=5.0, price=100.0)])
        order.order_line.qty_delivered = 5.0
        invoice = order._create_invoices()
        invoice.action_post()
        self.assertFalse(self._run(self._only(check_over_invoiced=True),
                                   order))

    def test_over_invoiced_silent_on_a_service_billed_on_order(self):
        # A service invoiced on the ordered quantity is meant to be
        # billed before anything is delivered, so the gap is normal.
        order = self._order([self._line(product=self.service, qty=1.0,
                                        price=200.0)])
        invoice = order._create_invoices()
        invoice.action_post()
        self.assertEqual(order.order_line.qty_invoiced, 1.0)
        self.assertEqual(order.order_line.qty_delivered, 0.0)
        self.assertFalse(self._run(self._only(check_over_invoiced=True),
                                   order))

    # ------------------------------------------------------------------
    # expired quotation still open
    # ------------------------------------------------------------------
    def test_expired_open_fires_on_a_stale_quotation(self):
        today = fields.Date.context_today(self.env.user)
        order = self._order([self._line()], confirm=False,
                            validity_date=today - timedelta(days=10))
        found = self._run(self._only(check_expired_open=True), order)
        self.assertEqual(len(found), 1)
        self.assertEqual(found.severity, "low")
        self.assertIn("10 days ago", found.message)

    def test_expired_open_silent_when_still_valid(self):
        today = fields.Date.context_today(self.env.user)
        order = self._order([self._line()], confirm=False,
                            validity_date=today + timedelta(days=10))
        self.assertFalse(self._run(self._only(check_expired_open=True),
                                   order))

    def test_expired_open_silent_with_no_validity_date(self):
        # A quotation with no expiry has none to miss.
        order = self._order([self._line()], confirm=False,
                            validity_date=False)
        self.assertFalse(self._run(self._only(check_expired_open=True),
                                   order))

    def test_expired_open_silent_once_confirmed(self):
        # A confirmed order is not waiting on anybody's answer.
        today = fields.Date.context_today(self.env.user)
        order = self._order([self._line()], confirm=True,
                            validity_date=today - timedelta(days=10))
        self.assertFalse(self._run(self._only(check_expired_open=True),
                                   order))

    # ------------------------------------------------------------------
    # no salesperson
    # ------------------------------------------------------------------
    def test_no_salesperson_fires_on_a_confirmed_order(self):
        order = self._order([self._line()])
        order.user_id = False
        found = self._run(self._only(check_no_salesperson=True), order)
        self.assertEqual(len(found), 1)
        self.assertEqual(found.check, "no_salesperson")

    def test_no_salesperson_silent_when_one_is_set(self):
        order = self._order([self._line()])
        self.assertFalse(self._run(self._only(check_no_salesperson=True),
                                   order))

    # ------------------------------------------------------------------
    # the whole thing, and the housekeeping around it
    # ------------------------------------------------------------------
    def test_a_clean_order_produces_nothing_with_every_check_on(self):
        """The case that decides whether anyone keeps the module.

        A healthy order, priced above cost, modestly discounted,
        delivered and invoiced, with a salesperson on it.
        """
        order = self._order([self._line(qty=5.0, price=100.0,
                                        discount=10.0)])
        order.order_line.qty_delivered = 5.0
        invoice = order._create_invoices()
        invoice.action_post()
        wizard = self._wizard(discount_limit=20.0, invoice_grace_days=7)
        self.assertFalse(self._run(wizard, order))

    def test_one_order_can_raise_several_findings(self):
        # Below cost at 50 against 60, and discounted 60% past a limit
        # of 20, is two separate problems on the same line.
        order = self._order([self._line(qty=10.0, price=125.0,
                                        discount=60.0)])
        found = self._run(self._wizard(discount_limit=20.0), order)
        checks = set(found.mapped("check"))
        self.assertIn("below_cost", checks)
        self.assertIn("discount_high", checks)
        # 125 less 60% is 50, against a cost of 60.
        below = found.filtered(lambda line: line.check == "below_cost")
        self.assertAlmostEqual(below.actual, 50.0, places=2)
        self.assertAlmostEqual(below.difference, -100.0, places=2)

    def test_note_and_count_report_what_was_scanned(self):
        self._order([self._line(qty=1.0, price=100.0)])
        wizard = self._wizard()
        wizard.action_run()
        self.assertTrue(wizard.has_run)
        self.assertGreaterEqual(wizard.order_count, 1)
        self.assertTrue(wizard.note)

    def test_running_twice_does_not_double_the_findings(self):
        order = self._order([self._line(qty=10.0, price=50.0)])
        wizard = self._only(check_below_cost=True)
        first = len(self._run(wizard, order))
        second = len(self._run(wizard, order))
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)

    def test_a_backwards_date_range_is_refused(self):
        from odoo.exceptions import UserError
        today = fields.Date.context_today(self.env.user)
        wizard = self._wizard(date_from=today, date_to=today -
                              timedelta(days=1))
        with self.assertRaises(UserError):
            wizard.action_run()

    def test_an_impossible_discount_limit_is_refused(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self._wizard(discount_limit=140.0).action_run()

    def test_sections_and_notes_are_skipped(self):
        """A section line has no product and no price, and must not be
        reported as a line priced at zero."""
        order = self._order([self._line(qty=1.0, price=100.0)],
                            confirm=False)
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "name": "A section heading",
            "display_type": "line_section",
        })
        order.action_confirm()
        self.assertFalse(self._run(self._only(check_zero_price=True), order))
