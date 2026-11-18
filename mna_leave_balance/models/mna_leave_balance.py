# Part of the Najjarine Tech Odoo modules. See LICENSE file for full copyright.
"""A leave balance that an employee can be shown without an apology.

Odoo knows the balance. It shows it as a number on a dashboard card, and
when somebody disputes that number there is no statement to put in front
of them. This builds one: allocated, taken, still awaiting approval, and
what is left, per employee and per leave type, with every movement behind
the figure listed underneath it.

Days and hours are both carried, because a leave type configured in hours
is meaningless expressed in days and the other way round.
"""
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

def _requires_allocation(leave_type):
    """18 declares this as a selection of yes and no, 19 as a boolean.
    Asking the value rather than the version keeps one source for both."""
    value = leave_type.requires_allocation
    return value is True or value == "yes"


TAKEN_STATES = ("validate",)
PENDING_STATES = ("confirm", "validate1")


class MnaLeaveBalance(models.TransientModel):
    _name = "mna.leave.balance"
    _description = "Time Off Balance"

    date_from = fields.Date(required=True, default=lambda s: fields.Date.context_today(s).replace(month=1, day=1))
    date_to = fields.Date(required=True, default=lambda s: fields.Date.context_today(s).replace(month=12, day=31))
    department_id = fields.Many2one("hr.department", string="Department")
    employee_ids = fields.Many2many("hr.employee", string="Employees",
                                    help="Leave empty for every employee, filtered by department if one is set.")
    holiday_status_ids = fields.Many2many("hr.leave.type", string="Time Off Types",
                                          help="Leave empty for every type.")
    include_pending = fields.Boolean(
        string="Hold requests awaiting approval", default=True,
        help="Requests submitted but not yet approved are held against the balance. "
             "Untick to count only what has actually been approved.")
    hide_empty = fields.Boolean(
        string="Hide types with no movement", default=True,
        help="An employee and type pair with nothing allocated and nothing taken is left out.")

    line_ids = fields.One2many("mna.leave.balance.line", "balance_id", readonly=True)
    ledger_ids = fields.One2many("mna.leave.balance.ledger", "balance_id", readonly=True)

    # -- computation ------------------------------------------------------

    def _employees(self):
        self.ensure_one()
        if self.employee_ids:
            return self.employee_ids
        domain = [("company_id", "in", self.env.companies.ids)]
        if self.department_id:
            domain.append(("department_id", "child_of", self.department_id.id))
        return self.env["hr.employee"].search(domain)

    def _allocation_domain(self, employees):
        """Allocations live in the period if they have started by its end
        and have not already ended before it began. An allocation with no
        end date runs forever, which is how Odoo itself reads it."""
        self.ensure_one()
        domain = [
            ("employee_id", "in", employees.ids),
            ("state", "=", "validate"),
            ("date_from", "<=", self.date_to),
            "|", ("date_to", "=", False), ("date_to", ">=", self.date_from),
        ]
        if self.holiday_status_ids:
            domain.append(("holiday_status_id", "in", self.holiday_status_ids.ids))
        return domain

    def _leave_domain(self, employees, states):
        self.ensure_one()
        domain = [
            ("employee_id", "in", employees.ids),
            ("state", "in", states),
            ("request_date_from", "<=", self.date_to),
            ("request_date_to", ">=", self.date_from),
        ]
        if self.holiday_status_ids:
            domain.append(("holiday_status_id", "in", self.holiday_status_ids.ids))
        return domain

    def action_compute(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(self.env._("The start date is after the end date."))
        self.line_ids.unlink()
        self.ledger_ids.unlink()

        employees = self._employees()
        if not employees:
            raise UserError(self.env._("No employee matches that selection."))

        figures = defaultdict(lambda: defaultdict(float))
        ledger = []

        allocations = self.env["hr.leave.allocation"].search(self._allocation_domain(employees))
        for allocation in allocations:
            key = (allocation.employee_id.id, allocation.holiday_status_id.id)
            figures[key]["allocated_days"] += allocation.number_of_days
            figures[key]["allocated_hours"] += allocation.number_of_hours_display
            ledger.append({
                "balance_id": self.id,
                "employee_id": allocation.employee_id.id,
                "holiday_status_id": allocation.holiday_status_id.id,
                "date": allocation.date_from,
                "kind": "allocation",
                "name": allocation.display_name,
                "days": allocation.number_of_days,
                "hours": allocation.number_of_hours_display,
                "state": allocation.state,
                "res_model": "hr.leave.allocation",
                "res_id": allocation.id,
            })

        states = TAKEN_STATES + (PENDING_STATES if self.include_pending else ())
        leaves = self.env["hr.leave"].search(self._leave_domain(employees, states))
        for leave in leaves:
            key = (leave.employee_id.id, leave.holiday_status_id.id)
            bucket = "taken" if leave.state in TAKEN_STATES else "pending"
            figures[key]["%s_days" % bucket] += leave.number_of_days
            figures[key]["%s_hours" % bucket] += leave.number_of_hours
            ledger.append({
                "balance_id": self.id,
                "employee_id": leave.employee_id.id,
                "holiday_status_id": leave.holiday_status_id.id,
                "date": leave.request_date_from,
                "kind": bucket,
                "name": leave.private_name or leave.display_name,
                "days": -leave.number_of_days,
                "hours": -leave.number_of_hours,
                "state": leave.state,
                "res_model": "hr.leave",
                "res_id": leave.id,
            })

        lines = []
        employee_by_id = {employee.id: employee for employee in employees}
        types = self.holiday_status_ids or self.env["hr.leave.type"].search([])
        for employee in employees:
            for leave_type in types:
                key = (employee.id, leave_type.id)
                figure = figures.get(key)
                if not figure and self.hide_empty:
                    continue
                figure = figure or {}
                allocated = figure.get("allocated_days", 0.0)
                taken = figure.get("taken_days", 0.0)
                pending = figure.get("pending_days", 0.0)
                # A type that needs no allocation has no balance to run
                # down. Subtracting anyway paints unlimited sick leave as
                # a deficit, which is worse than saying nothing.
                limited = _requires_allocation(leave_type)
                remaining = (allocated - taken - pending) if limited else 0.0
                remaining_hours = (
                    figure.get("allocated_hours", 0.0) - figure.get("taken_hours", 0.0)
                    - figure.get("pending_hours", 0.0)) if limited else 0.0
                lines.append({
                    "balance_id": self.id,
                    "employee_id": employee.id,
                    "department_id": employee_by_id[employee.id].department_id.id,
                    "holiday_status_id": leave_type.id,
                    "allocated_days": float_round(allocated, precision_digits=2),
                    "taken_days": float_round(taken, precision_digits=2),
                    "pending_days": float_round(pending, precision_digits=2),
                    "remaining_days": float_round(remaining, precision_digits=2),
                    "limited": limited,
                    "allocated_hours": float_round(figure.get("allocated_hours", 0.0), precision_digits=2),
                    "taken_hours": float_round(figure.get("taken_hours", 0.0), precision_digits=2),
                    "pending_hours": float_round(figure.get("pending_hours", 0.0), precision_digits=2),
                    "remaining_hours": float_round(remaining_hours, precision_digits=2),
                })

        self.env["mna.leave.balance.line"].create(lines)
        self.env["mna.leave.balance.ledger"].create(ledger)
        return {
            "type": "ir.actions.act_window",
            "res_model": "mna.leave.balance",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": self.env._("Time Off Balance"),
        }

    def action_open_ledger(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Time Off Ledger"),
            "res_model": "mna.leave.balance.ledger",
            "view_mode": "list",
            "domain": [("balance_id", "=", self.id)],
            "context": {"search_default_group_employee": 1},
        }


class MnaLeaveBalanceLine(models.TransientModel):
    _name = "mna.leave.balance.line"
    _description = "Time Off Balance Line"
    _order = "employee_id, holiday_status_id"

    balance_id = fields.Many2one("mna.leave.balance", required=True, ondelete="cascade", index=True)
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    department_id = fields.Many2one("hr.department", string="Department", readonly=True)
    holiday_status_id = fields.Many2one("hr.leave.type", string="Time Off Type", readonly=True)
    allocated_days = fields.Float(string="Allocated", readonly=True)
    taken_days = fields.Float(string="Taken", readonly=True)
    pending_days = fields.Float(string="Awaiting Approval", readonly=True)
    remaining_days = fields.Float(string="Remaining", readonly=True)
    limited = fields.Boolean(string="Counts against an allocation", readonly=True,
                             help="Types that need no allocation have no balance to run down.")
    allocated_hours = fields.Float(string="Allocated (h)", readonly=True)
    taken_hours = fields.Float(string="Taken (h)", readonly=True)
    pending_hours = fields.Float(string="Awaiting Approval (h)", readonly=True)
    remaining_hours = fields.Float(string="Remaining (h)", readonly=True)


class MnaLeaveBalanceLedger(models.TransientModel):
    _name = "mna.leave.balance.ledger"
    _description = "Time Off Ledger Entry"
    _order = "employee_id, holiday_status_id, date, id"

    balance_id = fields.Many2one("mna.leave.balance", required=True, ondelete="cascade", index=True)
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    holiday_status_id = fields.Many2one("hr.leave.type", string="Time Off Type", readonly=True)
    date = fields.Date(readonly=True)
    kind = fields.Selection([
        ("allocation", "Allocated"),
        ("taken", "Taken"),
        ("pending", "Awaiting approval"),
    ], string="Movement", readonly=True)
    name = fields.Char(string="Reference", readonly=True)
    days = fields.Float(string="Days", readonly=True)
    hours = fields.Float(string="Hours", readonly=True)
    state = fields.Char(string="Status", readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)

    def action_open_record(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "target": "current",
        }
