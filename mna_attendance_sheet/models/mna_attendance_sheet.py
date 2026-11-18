# Part of the Najjarine Tech Odoo modules. See LICENSE file for full copyright.
"""A monthly attendance sheet: one row per employee per working day.

Odoo records attendances and totals the hours. What it does not do is put
a day next to the day the employee was supposed to work, which is the
question every HR officer is actually asked: who came late, who left
early, and who did not come at all.

The planned day comes from the employee's working schedule
(``resource.calendar.attendance``), read directly rather than through the
calendar's interval helpers, because the attendance lines are stable
across Odoo 18 and 19 while the helper signatures are not.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round


def _localise(dt, tz):
    """A naive UTC datetime as a naive datetime in ``tz``."""
    return pytz.utc.localize(dt).astimezone(tz).replace(tzinfo=None)


def _hours(dt):
    """A datetime's clock time as hours since midnight, 13:30 -> 13.5."""
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


class MnaAttendanceSheet(models.TransientModel):
    _name = "mna.attendance.sheet"
    _description = "Attendance Sheet"

    date_from = fields.Date(required=True, default=lambda s: fields.Date.context_today(s).replace(day=1))
    date_to = fields.Date(required=True, default=lambda s: fields.Date.context_today(s))
    department_id = fields.Many2one("hr.department", string="Department")
    employee_ids = fields.Many2many("hr.employee", string="Employees",
                                    help="Leave empty for every employee, filtered by department if one is set.")
    grace_minutes = fields.Integer(
        string="Grace (minutes)", default=10,
        help="Minutes of lateness tolerated before a day is counted as late. "
             "The same tolerance applies to leaving early.")
    skip_days_off = fields.Boolean(
        string="Skip non-working days", default=True,
        help="Days the employee was not scheduled to work are left out. "
             "Untick to see attendances recorded outside the schedule.")

    line_ids = fields.One2many("mna.attendance.sheet.line", "sheet_id", readonly=True)
    summary_ids = fields.One2many("mna.attendance.sheet.summary", "sheet_id", readonly=True)

    # -- computation ------------------------------------------------------

    def _employees(self):
        self.ensure_one()
        if self.employee_ids:
            return self.employee_ids
        domain = [("company_id", "in", self.env.companies.ids)]
        if self.department_id:
            domain.append(("department_id", "child_of", self.department_id.id))
        return self.env["hr.employee"].search(domain)

    @api.model
    def _planned_for_weekday(self, calendar, weekday):
        """(start hour, end hour, hours) planned on ``weekday``, or None.

        Start and end are the earliest start and the latest end of the day,
        so a split shift reads as one span, while the hours total only the
        worked intervals and so excludes the lunch break between them.
        """
        if not calendar:
            return None
        lines = calendar.attendance_ids.filtered(lambda a: int(a.dayofweek) == weekday)
        # A two week calendar repeats the same hours in both weeks in all
        # but the unusual setups; taking both keeps one source of truth.
        if not lines:
            return None
        # The lunch line is a break, not work. Odoo takes it out of the
        # worked hours of an attendance, so counting it as expected would
        # show an hour owed every single day, which is the fastest way to
        # make a report nobody trusts. The span still runs from the first
        # line to the last, because somebody is late against the start of
        # their day, not against the start of the afternoon.
        working = lines.filtered(lambda a: a.day_period != "lunch") or lines
        start = min(working.mapped("hour_from"))
        end = max(working.mapped("hour_to"))
        hours = sum(max(0.0, line.hour_to - line.hour_from) for line in working)
        return start, end, hours

    def action_compute(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(self.env._("The start date is after the end date."))
        self.line_ids.unlink()
        self.summary_ids.unlink()

        employees = self._employees()
        if not employees:
            raise UserError(self.env._("No employee matches that selection."))

        grace = self.grace_minutes / 60.0
        attendances = self.env["hr.attendance"].search([
            ("employee_id", "in", employees.ids),
            ("check_in", "<=", datetime.combine(self.date_to + timedelta(days=1), time.max)),
            ("check_in", ">=", datetime.combine(self.date_from - timedelta(days=1), time.min)),
        ])

        # Bucket attendances by employee and by their local calendar date.
        by_day = defaultdict(list)
        for att in attendances:
            tz = pytz.timezone(att.employee_id.tz or "UTC")
            by_day[(att.employee_id.id, _localise(att.check_in, tz).date())].append(att)

        lines, summaries = [], []
        for employee in employees:
            tz = pytz.timezone(employee.tz or "UTC")
            calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id
            totals = defaultdict(float)
            day = self.date_from
            while day <= self.date_to:
                planned = self._planned_for_weekday(calendar, day.weekday())
                today = by_day.get((employee.id, day), [])
                day += timedelta(days=1)
                if not planned and self.skip_days_off:
                    continue

                expected = planned[2] if planned else 0.0
                worked = sum(a.worked_hours for a in today)
                first_in = last_out = False
                late = early = 0.0
                if today:
                    first_in = min(_localise(a.check_in, tz) for a in today)
                    closed = [a for a in today if a.check_out]
                    if closed:
                        last_out = max(_localise(a.check_out, tz) for a in closed)
                    if planned:
                        over = _hours(first_in) - planned[0]
                        if over > grace:
                            late = over * 60.0
                        if last_out:
                            short = planned[1] - _hours(last_out)
                            if short > grace:
                                early = short * 60.0

                if not today:
                    status = "absent"
                elif not last_out:
                    status = "open"
                elif late and early:
                    status = "late_early"
                elif late:
                    status = "late"
                elif early:
                    status = "early"
                else:
                    status = "ok"

                totals["expected"] += expected
                totals["worked"] += worked
                totals["late"] += late
                totals["early"] += early
                totals["n_" + status] += 1
                totals["days"] += 1

                lines.append({
                    "sheet_id": self.id,
                    "employee_id": employee.id,
                    "department_id": employee.department_id.id,
                    "date": day - timedelta(days=1),
                    "planned_from": planned[0] if planned else 0.0,
                    "planned_to": planned[1] if planned else 0.0,
                    "expected_hours": expected,
                    "check_in": _hours(first_in) if first_in else 0.0,
                    "check_out": _hours(last_out) if last_out else 0.0,
                    "worked_hours": worked,
                    "difference_hours": float_round(worked - expected, precision_digits=2),
                    "late_minutes": float_round(late, precision_digits=1),
                    "early_minutes": float_round(early, precision_digits=1),
                    "status": status,
                })

            if not totals["days"]:
                continue
            summaries.append({
                "sheet_id": self.id,
                "employee_id": employee.id,
                "department_id": employee.department_id.id,
                "working_days": int(totals["days"]),
                "days_present": int(totals["days"] - totals["n_absent"]),
                "days_absent": int(totals["n_absent"]),
                "days_late": int(totals["n_late"] + totals["n_late_early"]),
                "days_early": int(totals["n_early"] + totals["n_late_early"]),
                "days_open": int(totals["n_open"]),
                "expected_hours": float_round(totals["expected"], precision_digits=2),
                "worked_hours": float_round(totals["worked"], precision_digits=2),
                "difference_hours": float_round(totals["worked"] - totals["expected"], precision_digits=2),
                "late_minutes": float_round(totals["late"], precision_digits=1),
                "early_minutes": float_round(totals["early"], precision_digits=1),
            })

        self.env["mna.attendance.sheet.line"].create(lines)
        self.env["mna.attendance.sheet.summary"].create(summaries)
        return {
            "type": "ir.actions.act_window",
            "res_model": "mna.attendance.sheet",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": self.env._("Attendance Sheet"),
            "context": dict(self.env.context, mna_computed=True),
        }

    def action_open_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Attendance Detail"),
            "res_model": "mna.attendance.sheet.line",
            "view_mode": "list,pivot",
            "domain": [("sheet_id", "=", self.id)],
            "context": {"search_default_group_employee": 1},
        }


class MnaAttendanceSheetLine(models.TransientModel):
    # The four clock time fields carry aggregator=None. They are times of
    # day, and a grouped list that adds them up reports a planned start of
    # 104:00, which is the sort of number that makes a reader distrust the
    # columns that are right.
    _name = "mna.attendance.sheet.line"
    _description = "Attendance Sheet Line"
    _order = "employee_id, date"

    sheet_id = fields.Many2one("mna.attendance.sheet", required=True, ondelete="cascade", index=True)
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    department_id = fields.Many2one("hr.department", string="Department", readonly=True)
    date = fields.Date(readonly=True)
    planned_from = fields.Float(string="Planned In", readonly=True, aggregator=None)
    planned_to = fields.Float(string="Planned Out", readonly=True, aggregator=None)
    expected_hours = fields.Float(string="Expected", readonly=True)
    check_in = fields.Float(string="First In", readonly=True, aggregator=None)
    check_out = fields.Float(string="Last Out", readonly=True, aggregator=None)
    worked_hours = fields.Float(string="Worked", readonly=True)
    difference_hours = fields.Float(string="Difference", readonly=True)
    late_minutes = fields.Float(string="Late (min)", readonly=True)
    early_minutes = fields.Float(string="Left Early (min)", readonly=True)
    status = fields.Selection([
        ("ok", "On time"),
        ("late", "Late"),
        ("early", "Left early"),
        ("late_early", "Late and left early"),
        ("open", "Never checked out"),
        ("absent", "Absent"),
    ], readonly=True)


class MnaAttendanceSheetSummary(models.TransientModel):
    _name = "mna.attendance.sheet.summary"
    _description = "Attendance Sheet Summary"
    _order = "employee_id"

    sheet_id = fields.Many2one("mna.attendance.sheet", required=True, ondelete="cascade", index=True)
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    department_id = fields.Many2one("hr.department", string="Department", readonly=True)
    working_days = fields.Integer(string="Days", readonly=True)
    days_present = fields.Integer(string="Present", readonly=True)
    days_absent = fields.Integer(string="Absent", readonly=True)
    days_late = fields.Integer(string="Late", readonly=True)
    days_early = fields.Integer(string="Left Early", readonly=True)
    days_open = fields.Integer(string="No Check Out", readonly=True)
    expected_hours = fields.Float(string="Expected", readonly=True)
    worked_hours = fields.Float(string="Worked", readonly=True)
    difference_hours = fields.Float(string="Difference", readonly=True)
    late_minutes = fields.Float(string="Late (min)", readonly=True)
    early_minutes = fields.Float(string="Left Early (min)", readonly=True)
