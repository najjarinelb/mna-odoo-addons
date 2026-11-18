from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosMultiCurrency(TestPoSCommon):
    """Money arithmetic, so the figures are checked against hand sums.

    The rate used throughout is 89,000 of the second currency to one of
    the shop's, which is the order of magnitude this module exists for.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.product = cls.create_product("Bread", cls.categ_basic, 2.0, 1.0)
        cls.foreign = cls.env["res.currency"].with_context(active_test=False).search(
            [("name", "=", "LBP")], limit=1
        )
        if not cls.foreign:
            cls.foreign = cls.env["res.currency"].create({
                "name": "LBP", "symbol": "LL", "rounding": 1000.0,
            })
        cls.foreign.active = True
        cls.method = cls.env["pos.payment.method"].create({
            "name": "Cash LBP",
            "journal_id": cls.cash_journal.id if hasattr(cls, "cash_journal")
            else cls.company_data["default_journal_cash"].id,
            "company_id": cls.env.company.id,
            "mna_foreign_currency_id": cls.foreign.id,
            "mna_rate_mode": "fixed",
            "mna_fixed_rate": 89000.0,
        })
        # A payment method only works in a session whose config offers it,
        # which is Odoo being right rather than the test being awkward.
        cls.config.write({"payment_method_ids": [(4, cls.method.id)]})

    def _order_with_payment(self, foreign_amount=None, shop_amount=None, total=2.0):
        self.open_new_session()
        session = self.pos_session
        order = self.env["pos.order"].create({
            "session_id": session.id,
            "company_id": self.env.company.id,
            "amount_tax": 0.0, "amount_total": total,
            "amount_paid": 0.0, "amount_return": 0.0,
            "lines": [(0, 0, {
                "product_id": self.product.id, "qty": 1,
                "price_unit": total, "price_subtotal": total,
                "price_subtotal_incl": total, "total_cost": 1.0,
            })],
        })
        values = {
            "pos_order_id": order.id,
            "payment_method_id": self.method.id,
            "amount": shop_amount or 0.0,
        }
        if foreign_amount is not None:
            values["mna_amount_foreign"] = foreign_amount
        payment = self.env["pos.payment"].create(values)
        return order, payment

    # ------------------------------------------------------------------
    def test_01_foreign_amount_converts_to_the_shop_currency(self):
        """178,000 at 89,000 to the unit is exactly 2.00."""
        _order, payment = self._order_with_payment(foreign_amount=178000.0)
        self.assertAlmostEqual(payment.amount, 2.0)
        self.assertAlmostEqual(payment.mna_amount_foreign, 178000.0)
        self.assertAlmostEqual(payment.mna_rate_used, 89000.0)
        self.assertEqual(payment.mna_foreign_currency_id, self.foreign)

    def test_02_a_shop_amount_is_shown_in_the_other_currency_too(self):
        """Entered the other way round, both figures still end up on the line."""
        _order, payment = self._order_with_payment(shop_amount=2.0)
        self.assertAlmostEqual(payment.amount, 2.0)
        self.assertAlmostEqual(payment.mna_amount_foreign, 178000.0)

    def test_03_the_server_does_not_trust_the_browser(self):
        """A stale tab sending both figures gets the server's arithmetic.

        This is the whole reason the conversion is repeated server side:
        a till left open overnight would otherwise book today's takings
        at yesterday's rate.
        """
        _order, payment = self._order_with_payment(
            foreign_amount=178000.0, shop_amount=999.0
        )
        self.assertAlmostEqual(
            payment.amount, 2.0,
            msg="the amount must be derived from the foreign amount, not accepted",
        )

    def test_04_the_rate_is_frozen_onto_the_payment(self):
        """A receipt reprinted after a devaluation shows the old rate."""
        _order, payment = self._order_with_payment(foreign_amount=178000.0)
        # Odoo refuses to edit a payment method while a session is open,
        # rightly, so the later rate change is applied underneath it to
        # reproduce what a devaluation does over a weekend.
        self.env.cr.execute(
            "UPDATE pos_payment_method SET mna_fixed_rate = 100000 WHERE id = %s",
            (self.method.id,),
        )
        self.env.invalidate_all()
        self.assertAlmostEqual(payment.mna_rate_used, 89000.0)
        self.assertAlmostEqual(payment.amount, 2.0)

    def test_05_a_live_rate_follows_the_currency(self):
        method = self.method.copy({
            "name": "Cash LBP live", "mna_rate_mode": "live", "mna_fixed_rate": 0.0,
        })
        self.env["res.currency.rate"].create({
            "name": "2020-01-01",
            "currency_id": self.foreign.id,
            "rate": 50000.0,
            "company_id": self.env.company.id,
        })
        self.assertAlmostEqual(method._mna_rate(), 50000.0, places=2)

    def test_06_an_ordinary_method_is_untouched(self):
        self.open_new_session()
        session = self.pos_session
        order = self.env["pos.order"].create({
            "session_id": session.id, "company_id": self.env.company.id,
            "amount_tax": 0.0, "amount_total": 2.0,
            "amount_paid": 0.0, "amount_return": 0.0,
            "lines": [(0, 0, {
                "product_id": self.product.id, "qty": 1, "price_unit": 2.0,
                "price_subtotal": 2.0, "price_subtotal_incl": 2.0,
            })],
        })
        cash = session.payment_method_ids.filtered("is_cash_count")[:1]
        payment = self.env["pos.payment"].create({
            "pos_order_id": order.id,
            "payment_method_id": cash.id,
            "amount": 2.0,
        })
        self.assertAlmostEqual(payment.amount, 2.0)
        self.assertFalse(payment.mna_foreign_currency_id)
        self.assertAlmostEqual(payment.mna_amount_foreign, 0.0)

    def test_07_the_shop_currency_cannot_be_the_payment_currency(self):
        with self.assertRaises(ValidationError):
            self.method.write({
                "mna_foreign_currency_id": self.env.company.currency_id.id,
            })

    def test_08_a_fixed_rate_must_be_set(self):
        with self.assertRaises(ValidationError):
            self.method.write({"mna_rate_mode": "fixed", "mna_fixed_rate": 0.0})

    def test_09_session_totals_what_came_in_per_currency(self):
        order, _payment = self._order_with_payment(foreign_amount=178000.0)
        session = order.session_id
        self.env["pos.payment"].create({
            "pos_order_id": order.id,
            "payment_method_id": self.method.id,
            "mna_amount_foreign": 89000.0,
        })
        session._mna_rebuild_foreign_lines()

        line = session.mna_foreign_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.currency_id, self.foreign)
        self.assertEqual(line.payment_count, 2)
        self.assertAlmostEqual(line.amount_foreign, 267000.0)
        self.assertAlmostEqual(line.amount_shop, 3.0)

    def test_10_counting_the_till_shows_the_difference(self):
        order, _payment = self._order_with_payment(foreign_amount=178000.0)
        session = order.session_id
        session._mna_rebuild_foreign_lines()
        line = session.mna_foreign_line_ids
        line.counted_foreign = 170000.0
        self.assertAlmostEqual(line.difference_foreign, -8000.0)

    def test_11_change_bigger_than_the_sale_is_refused(self):
        """What a rate typed into the amount box looks like."""
        from odoo.exceptions import UserError
        order, _payment = self._order_with_payment(
            foreign_amount=89000000.0, total=2.0
        )
        order.invalidate_recordset()
        with self.assertRaises(UserError):
            order._mna_check_change()

    def test_12_a_normal_sale_passes_the_change_guard(self):
        order, _payment = self._order_with_payment(foreign_amount=178000.0, total=2.0)
        order.invalidate_recordset()
        order._mna_check_change()
