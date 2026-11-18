# Part of the Najjarine Tech Odoo modules. See LICENSE file for full copyright.
"""The figures below are small on purpose so they can be checked by eye.

One employee on the standard 40 hour week (eight hours a day). Twenty days
allocated. Three days approved. Two days submitted and not yet approved.
So twenty minus three minus two is fifteen remaining, and seventeen if
pending requests are not held.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeaveBalance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 18 declares requires_allocation as a selection, 19 as a boolean.
        # One source for both branches means asking the field, not the
        # version number.
        field = cls.env["hr.leave.type"]._fields["requires_allocation"]
        no_allocation_needed = False if field.type == "boolean" else "no"

        allocation_needed = True if field.type == "boolean" else "yes"
        cls.leave_type = cls.env["hr.leave.type"].create({
            "name": "MNA Annual",
            "requires_allocation": allocation_needed,
            "leave_validation_type": "hr",
            "request_unit": "day",
        })
        cls.other_type = cls.env["hr.leave.type"].create({
            "name": "MNA Unpaid",
            "requires_allocation": no_allocation_needed,
            "leave_validation_type": "hr",
            "request_unit": "day",
        })
        cls.employee = cls.env["hr.employee"].create({"name": "Rana Khalil"})

        cls.allocation = cls.env["hr.leave.allocation"].create({
            "name": "2025 annual leave",
            "employee_id": cls.employee.id,
            "holiday_status_id": cls.leave_type.id,
            "number_of_days": 20.0,
            "date_from": "2025-01-01",
        })
        cls.allocation.state = "validate"

        cls.taken = cls._leave("2025-03-03", "2025-03-05", "validate")    # Mon to Wed
        cls.pending = cls._leave("2025-04-07", "2025-04-08", "confirm")   # Mon to Tue
        cls.refused = cls._leave("2025-05-05", "2025-05-09", "refuse")    # a whole week

    @classmethod
    def _leave(cls, date_from, date_to, state):
        leave = cls.env["hr.leave"].create({
            "name": "Leave %s" % date_from,
            "employee_id": cls.employee.id,
            "holiday_status_id": cls.leave_type.id,
            "request_date_from": date_from,
            "request_date_to": date_to,
        })
        leave.state = state
        return leave

    def _balance(self, **values):
        balance = self.env["mna.leave.balance"].create(dict({
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
            "employee_ids": [(6, 0, self.employee.ids)],
        }, **values))
        balance.action_compute()
        return balance

    def _annual(self, balance):
        return balance.line_ids.filtered(lambda l: l.holiday_status_id == self.leave_type)

    # -- the balance ------------------------------------------------------

    def test_days(self):
        """20 allocated, 3 approved, 2 pending, so 15 left."""
        line = self._annual(self._balance())
        self.assertAlmostEqual(line.allocated_days, 20.0, places=2)
        self.assertAlmostEqual(line.taken_days, 3.0, places=2)
        self.assertAlmostEqual(line.pending_days, 2.0, places=2)
        self.assertAlmostEqual(line.remaining_days, 15.0, places=2)
        self.assertTrue(line.limited)

    def test_hours(self):
        """Eight hours a day: 160 allocated, 24 taken, 16 pending, 120 left."""
        line = self._annual(self._balance())
        self.assertAlmostEqual(line.allocated_hours, 160.0, places=2)
        self.assertAlmostEqual(line.taken_hours, 24.0, places=2)
        self.assertAlmostEqual(line.pending_hours, 16.0, places=2)
        self.assertAlmostEqual(line.remaining_hours, 120.0, places=2)

    def test_pending_can_be_left_out(self):
        """Counting only what is approved leaves 20 minus 3, which is 17."""
        line = self._annual(self._balance(include_pending=False))
        self.assertAlmostEqual(line.pending_days, 0.0, places=2)
        self.assertAlmostEqual(line.remaining_days, 17.0, places=2)

    def test_refused_requests_do_not_count(self):
        """The refused week is five days that must not touch the balance."""
        balance = self._balance()
        self.assertAlmostEqual(self._annual(balance).taken_days, 3.0, places=2)
        self.assertFalse(balance.ledger_ids.filtered(lambda l: l.res_id == self.refused.id))

    def test_draft_allocation_does_not_count(self):
        """A plan is not a balance: an allocation still awaiting approval
        contributes nothing."""
        colleague = self.env["hr.employee"].create({"name": "Tarek Awad"})
        self.env["hr.leave.allocation"].create({
            "name": "2025 annual leave, not yet approved",
            "employee_id": colleague.id,
            "holiday_status_id": self.leave_type.id,
            "number_of_days": 12.0,
            "date_from": "2025-01-01",
        })
        balance = self.env["mna.leave.balance"].create({
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
            "employee_ids": [(6, 0, colleague.ids)],
            "hide_empty": False,
        })
        balance.action_compute()
        line = balance.line_ids.filtered(lambda l: l.holiday_status_id == self.leave_type)
        self.assertAlmostEqual(line.allocated_days, 0.0, places=2)
        self.assertAlmostEqual(line.remaining_days, 0.0, places=2)

    # -- the period -------------------------------------------------------

    def test_period_before_the_movements_is_empty(self):
        """A 2024 report must not pick up 2025 leave."""
        balance = self._balance(date_from="2024-01-01", date_to="2024-12-31")
        self.assertFalse(balance.line_ids)
        self.assertFalse(balance.ledger_ids)

    def test_a_request_overlapping_the_edge_counts(self):
        """The March leave is inside a period that ends mid March."""
        line = self._annual(self._balance(date_from="2025-01-01", date_to="2025-03-04"))
        self.assertAlmostEqual(line.taken_days, 3.0, places=2)
        self.assertAlmostEqual(line.pending_days, 0.0, places=2)

    # -- the ledger -------------------------------------------------------

    def test_ledger(self):
        """One allocation in, two requests out, signed so the column adds up."""
        balance = self._balance()
        ledger = balance.ledger_ids.filtered(lambda l: l.holiday_status_id == self.leave_type)
        self.assertEqual(len(ledger), 3)
        self.assertAlmostEqual(sum(ledger.mapped("days")), 15.0, places=2)
        allocation_line = ledger.filtered(lambda l: l.kind == "allocation")
        self.assertAlmostEqual(allocation_line.days, 20.0, places=2)
        self.assertEqual(allocation_line.res_model, "hr.leave.allocation")
        self.assertEqual(allocation_line.res_id, self.allocation.id)

    def test_ledger_button_opens_the_record(self):
        balance = self._balance()
        line = balance.ledger_ids.filtered(lambda l: l.kind == "allocation")
        action = line.action_open_record()
        self.assertEqual(action["res_model"], "hr.leave.allocation")
        self.assertEqual(action["res_id"], self.allocation.id)

    # -- the options ------------------------------------------------------

    def test_empty_types_are_hidden_by_default(self):
        balance = self._balance()
        self.assertNotIn(self.other_type, balance.line_ids.mapped("holiday_status_id"))

    def test_empty_types_can_be_shown(self):
        balance = self._balance(hide_empty=False)
        line = balance.line_ids.filtered(lambda l: l.holiday_status_id == self.other_type)
        self.assertTrue(line)
        self.assertEqual(line.allocated_days, 0.0)
        self.assertEqual(line.remaining_days, 0.0)

    def test_dates_the_wrong_way_round_are_refused(self):
        with self.assertRaises(UserError):
            self._balance(date_from="2025-12-31", date_to="2025-01-01")

    # -- types that have no balance to run down ---------------------------

    def test_a_type_needing_no_allocation_shows_no_deficit(self):
        """Two days of a type with no allocation is two days taken, not
        minus two days remaining."""
        self._leave("2025-06-02", "2025-06-03", "validate")
        unlimited = self.env["hr.leave.type"].browse(self.other_type.id)
        leave = self.env["hr.leave"].create({
            "name": "Unpaid",
            "employee_id": self.employee.id,
            "holiday_status_id": unlimited.id,
            "request_date_from": "2025-06-09",
            "request_date_to": "2025-06-10",
        })
        leave.state = "validate"
        line = self._balance().line_ids.filtered(lambda l: l.holiday_status_id == unlimited)
        self.assertFalse(line.limited)
        self.assertAlmostEqual(line.taken_days, 2.0, places=2)
        self.assertAlmostEqual(line.remaining_days, 0.0, places=2)
