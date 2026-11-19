# Part of the Najjarine Tech Odoo modules.
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMrpOrderCheck(TransactionCase):
    """The point of these tests is the clean case.

    A check that fires on healthy data is worse than no check, so the
    first test asserts silence on a correctly closed order and every
    later test asserts that exactly one thing was found.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.company = cls.env.company
        Product = cls.env["product.product"]
        cls.bolt = Product.create({
            "name": "MNA Bolt", "is_storable": True,
            "standard_price": 2.0, "uom_id": cls.unit.id})
        cls.plate = Product.create({
            "name": "MNA Plate", "is_storable": True,
            "standard_price": 7.5, "uom_id": cls.unit.id})
        cls.frame = Product.create({
            "name": "MNA Frame", "is_storable": True,
            "standard_price": 0.0, "uom_id": cls.unit.id})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.frame.product_tmpl_id.id,
            "product_id": cls.frame.id,
            "product_qty": 1.0,
            "product_uom_id": cls.unit.id,
            "type": "normal",
            "consumption": "warning",
            "bom_line_ids": [
                (0, 0, {"product_id": cls.bolt.id, "product_qty": 4.0,
                        "product_uom_id": cls.unit.id}),
                (0, 0, {"product_id": cls.plate.id, "product_qty": 1.0,
                        "product_uom_id": cls.unit.id}),
            ],
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_order(self, qty=10.0, bom=None):
        order = self.env["mrp.production"].create({
            "product_id": self.frame.id,
            "product_qty": qty,
            "product_uom_id": self.unit.id,
            "bom_id": (bom or self.bom).id,
        })
        order.action_confirm()
        return order

    def _finish(self, order, producing=None, consumption=None):
        """Close an order, optionally overriding consumed quantities.

        consumption is {product: qty}. Anything not named is consumed at
        the quantity the bill of materials asked for.
        """
        order.qty_producing = producing if producing is not None \
            else order.product_qty
        order._set_qty_producing()
        for move in order.move_raw_ids:
            if consumption and move.product_id in consumption:
                move.quantity = consumption[move.product_id]
            move.picked = True
        order.with_context(skip_consumption=True,
                           skip_backorder=True).button_mark_done()
        return order

    def _run(self, **kwargs):
        today = fields.Date.context_today(self.env.user)
        values = {
            "date_from": today.replace(day=1),
            "date_to": today,
            "company_id": self.company.id,
        }
        values.update(kwargs)
        wizard = self.env["mna.mrp.order.check"].create(values)
        wizard.action_run()
        return wizard

    def _findings(self, wizard, order):
        return wizard.line_ids.filtered(
            lambda line: line.production_id == order)

    def _kinds(self, wizard, order):
        return set(self._findings(wizard, order).mapped("check"))

    # ------------------------------------------------------------------
    # the clean case, which matters most
    # ------------------------------------------------------------------
    def test_clean_order_reports_nothing(self):
        """Ordered 10, produced 10, consumed 40 bolts and 10 plates.

        BoM is 4 bolts and 1 plate per unit, so 10 units is 40 and 10.
        Both components carry a cost. Nothing here is wrong, and the
        report has to say so.
        """
        order = self._make_order(10.0)
        self._finish(order)
        self.assertEqual(order.state, "done")
        bolts = sum(order.move_raw_ids.filtered(
            lambda m: m.product_id == self.bolt).mapped("quantity"))
        self.assertAlmostEqual(bolts, 40.0, 4,
                               "Setup check: 10 units at 4 bolts each.")
        wizard = self._run()
        self.assertEqual(self._findings(wizard, order),
                         self.env["mna.mrp.order.check.line"],
                         "A correctly closed order must produce no "
                         "findings at all. %s" % self._kinds(wizard, order))
        self.assertIn("Nothing to report", wizard.note)
        self.assertEqual(wizard.order_count, 1)

    # ------------------------------------------------------------------
    # one rule at a time
    # ------------------------------------------------------------------
    def test_quantity_mismatch(self):
        """Ordered 10, produced 8, so the difference is -2."""
        order = self._make_order(10.0)
        self._finish(order, producing=8.0)
        wizard = self._run()
        found = self._findings(wizard, order).filtered(
            lambda line: line.check == "qty_mismatch")
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found.planned_qty, 10.0, 4)
        self.assertAlmostEqual(found.actual_qty, 8.0, 4)
        self.assertAlmostEqual(found.difference, -2.0, 4)
        self.assertEqual(found.severity, "high")

    def test_component_never_consumed(self):
        """40 bolts planned, none consumed."""
        order = self._make_order(10.0)
        self._finish(order, consumption={self.bolt: 0.0})
        wizard = self._run()
        found = self._findings(wizard, order).filtered(
            lambda line: line.check == "not_consumed")
        self.assertEqual(len(found), 1)
        self.assertEqual(found.product_id, self.bolt)
        self.assertAlmostEqual(found.planned_qty, 40.0, 4)
        self.assertAlmostEqual(found.actual_qty, 0.0, 4)
        # And it is not also reported as over-consumed, which would be
        # the same problem counted twice.
        self.assertNotIn("over_consumed", self._kinds(wizard, order))

    def test_over_consumption_past_tolerance(self):
        """50 bolts against a plan of 40 is 25% over, so it is reported.

        plan   = 10 units * 4 bolts = 40
        actual = 50
        over   = (50 - 40) / 40 = 25%
        """
        order = self._make_order(10.0)
        self._finish(order, consumption={self.bolt: 50.0})
        wizard = self._run(over_consumption_tolerance=10.0)
        found = self._findings(wizard, order).filtered(
            lambda line: line.check == "over_consumed")
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found.planned_qty, 40.0, 4)
        self.assertAlmostEqual(found.actual_qty, 50.0, 4)
        self.assertAlmostEqual(found.difference, 10.0, 4)
        self.assertIn("25.0%", found.message)

    def test_over_consumption_within_tolerance_is_silent(self):
        """42 bolts against 40 is 5% over, which is scrap, not a problem.

        A tolerance that does not actually suppress anything is just a
        field on a form, so this is the test that earns it.
        """
        order = self._make_order(10.0)
        self._finish(order, consumption={self.bolt: 42.0})
        wizard = self._run(over_consumption_tolerance=10.0)
        self.assertNotIn("over_consumed", self._kinds(wizard, order))
        # Tighten the tolerance below 5% and the same order is reported,
        # which proves the suppression came from the tolerance and not
        # from the rule failing to fire at all.
        tight = self._run(over_consumption_tolerance=1.0)
        self.assertIn("over_consumed", self._kinds(tight, order))

    def test_flexible_consumption_bom_is_not_nagged(self):
        """A BoM set to flexible is meant to vary, so leave it alone."""
        flexible = self.bom.copy({"consumption": "flexible"})
        order = self._make_order(10.0, bom=flexible)
        self._finish(order, consumption={self.bolt: 80.0})
        wizard = self._run(over_consumption_tolerance=10.0)
        self.assertNotIn("over_consumed", self._kinds(wizard, order),
                         "Flexible consumption was chosen on purpose and "
                         "arguing with it is noise.")

    def test_zero_cost_component(self):
        order = self._make_order(10.0)
        self.plate.standard_price = 0.0
        self._finish(order)
        wizard = self._run()
        found = self._findings(wizard, order).filtered(
            lambda line: line.check == "zero_cost")
        self.assertEqual(found.mapped("product_id"), self.plate)
        self.assertEqual(found.severity, "low")
        # Restore and the finding goes away.
        self.plate.standard_price = 7.5
        self.assertNotIn("zero_cost", self._kinds(self._run(), order))

    def test_work_orders_with_no_time_logged(self):
        """60 minutes planned across work orders, none logged."""
        workcenter = self.env["mrp.workcenter"].create({
            "name": "MNA Assembly Bench", "costs_hour": 45.0})
        routed = self.bom.copy()
        self.env["mrp.routing.workcenter"].create({
            "name": "Assemble", "bom_id": routed.id,
            "workcenter_id": workcenter.id, "time_cycle_manual": 60.0,
            "time_mode": "manual"})
        order = self._make_order(1.0, bom=routed)
        self.assertTrue(order.workorder_ids,
                        "Setup check: the routing has to create a work "
                        "order or this test proves nothing.")
        order.workorder_ids.duration_expected = 60.0
        self._finish(order, producing=1.0)
        order.workorder_ids.duration = 0.0
        wizard = self._run()
        found = self._findings(wizard, order).filtered(
            lambda line: line.check == "no_duration")
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found.planned_qty, 60.0, 2)
        self.assertAlmostEqual(found.actual_qty, 0.0, 2)

    def test_work_orders_with_time_logged_are_silent(self):
        workcenter = self.env["mrp.workcenter"].create({
            "name": "MNA Press", "costs_hour": 45.0})
        routed = self.bom.copy()
        self.env["mrp.routing.workcenter"].create({
            "name": "Press", "bom_id": routed.id,
            "workcenter_id": workcenter.id, "time_cycle_manual": 30.0,
            "time_mode": "manual"})
        order = self._make_order(1.0, bom=routed)
        order.workorder_ids.duration_expected = 30.0
        self._finish(order, producing=1.0)
        order.workorder_ids.duration = 34.0
        wizard = self._run()
        self.assertNotIn("no_duration", self._kinds(wizard, order))

    def test_order_with_no_routing_is_not_reported_for_time(self):
        """No work orders means no labour to lose, so stay quiet."""
        order = self._make_order(5.0)
        self._finish(order)
        self.assertFalse(order.workorder_ids)
        wizard = self._run()
        self.assertNotIn("no_duration", self._kinds(wizard, order))

    # ------------------------------------------------------------------
    # scoping and input
    # ------------------------------------------------------------------
    def test_disabled_check_does_not_run(self):
        order = self._make_order(10.0)
        self._finish(order, producing=8.0)
        wizard = self._run(check_qty_mismatch=False)
        self.assertNotIn("qty_mismatch", self._kinds(wizard, order))

    def test_order_outside_the_period_is_not_scanned(self):
        order = self._make_order(10.0)
        self._finish(order, producing=8.0)
        today = fields.Date.context_today(self.env.user)
        past = today.replace(day=1) - relativedelta(
            months=2)
        wizard = self._run(date_from=past,
                           date_to=past + relativedelta(
                               days=5))
        self.assertEqual(wizard.order_count, 0)
        self.assertEqual(wizard.line_ids,
                         self.env["mna.mrp.order.check.line"])

    def test_reversed_dates_are_rejected(self):
        today = fields.Date.context_today(self.env.user)
        wizard = self.env["mna.mrp.order.check"].create({
            "date_from": today,
            "date_to": today - relativedelta(days=5),
            "company_id": self.company.id,
        })
        with self.assertRaises(UserError):
            wizard.action_run()

    def test_unfinished_order_is_not_scanned(self):
        order = self._make_order(10.0)
        self.assertEqual(order.state, "confirmed")
        wizard = self._run()
        self.assertEqual(self._findings(wizard, order),
                         self.env["mna.mrp.order.check.line"],
                         "An order still in progress has not gone wrong "
                         "yet and must not be reported.")
