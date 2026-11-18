# Part of the Najjarine Tech Odoo modules. See LICENSE file for full copyright.
"""The arithmetic is written out in the assertions on purpose.

Every figure below can be checked by hand from the fixture: a Beirut
employee (UTC+2 in January, so no daylight saving to argue about) on a
Monday to Friday schedule of 08:00 to 12:00 and 13:00 to 17:00, which is
eight expected hours a day and a planned span of 08:00 to 17:00.
"""
from datetime import datetime

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceSheet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "MNA Test 08-17 Beirut",
            "tz": "Asia/Beirut",
            "hours_per_day": 8.0,
            "attendance_ids": [(5, 0, 0)] + [
                (0, 0, {
                    "name": "%s %s" % (day, part),
                    "dayofweek": str(day),
                    "hour_from": hour_from,
                    "hour_to": hour_to,
                    "day_period": part,
                })
                for day in range(0, 5)
                for part, hour_from, hour_to in (
                    ("morning", 8.0, 12.0),
                    ("afternoon", 13.0, 17.0),
                )
            ],
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Sami Haddad",
            "tz": "Asia/Beirut",
            "resource_calendar_id": cls.calendar.id,
        })
        # Beirut is UTC+2 in January, so local = UTC + 2.
        for check_in, check_out in (
            ("2025-01-06 06:00:00", "2025-01-06 15:00:00"),   # Mon 08:00-17:00 on time
            ("2025-01-07 06:25:00", "2025-01-07 14:30:00"),   # Tue 08:25-16:30 late and early
            # Wed: nothing at all, an absence
            ("2025-01-09 06:00:00", None),                     # Thu 08:00 and never out
            ("2025-01-10 06:08:00", "2025-01-10 15:00:00"),   # Fri 08:08-17:00, inside the grace
        ):
            cls.env["hr.attendance"].create({
                "employee_id": cls.employee.id,
                "check_in": datetime.strptime(check_in, "%Y-%m-%d %H:%M:%S"),
                "check_out": datetime.strptime(check_out, "%Y-%m-%d %H:%M:%S") if check_out else False,
            })

    def _sheet(self, **values):
        sheet = self.env["mna.attendance.sheet"].create(dict({
            "date_from": "2025-01-06",
            "date_to": "2025-01-12",
            "employee_ids": [(6, 0, self.employee.ids)],
            "grace_minutes": 10,
        }, **values))
        sheet.action_compute()
        return sheet

    def _by_date(self, sheet):
        return {str(line.date): line for line in sheet.line_ids}

    # -- the days ---------------------------------------------------------

    def test_weekend_is_not_a_working_day(self):
        """Seven days in the range, five of them scheduled."""
        sheet = self._sheet()
        self.assertEqual(len(sheet.line_ids), 5)
        self.assertNotIn("2025-01-11", self._by_date(sheet))  # Saturday
        self.assertNotIn("2025-01-12", self._by_date(sheet))  # Sunday

    def test_clean_day_is_not_flagged(self):
        """08:00 to 17:00 against a planned 08:00 to 17:00 is nothing to report."""
        line = self._by_date(self._sheet())["2025-01-06"]
        self.assertEqual(line.status, "ok")
        self.assertEqual(line.late_minutes, 0.0)
        self.assertEqual(line.early_minutes, 0.0)
        self.assertEqual(line.planned_from, 8.0)
        self.assertEqual(line.planned_to, 17.0)
        self.assertEqual(line.check_in, 8.0)
        self.assertEqual(line.check_out, 17.0)
        # 08:00 to 17:00 is nine hours against eight expected, so plus one.
        self.assertAlmostEqual(line.expected_hours, 8.0, places=2)
        self.assertAlmostEqual(line.worked_hours, 9.0, places=2)
        self.assertAlmostEqual(line.difference_hours, 1.0, places=2)

    def test_late_and_early_on_the_same_day(self):
        """08:25 is 25 minutes late; 16:30 is 30 minutes early."""
        line = self._by_date(self._sheet())["2025-01-07"]
        self.assertEqual(line.status, "late_early")
        self.assertAlmostEqual(line.late_minutes, 25.0, places=1)
        self.assertAlmostEqual(line.early_minutes, 30.0, places=1)
        # 08:25 to 16:30 is 8h05m, five minutes over the eight expected.
        self.assertAlmostEqual(line.worked_hours, 8.0 + 5.0 / 60.0, places=3)
        self.assertAlmostEqual(line.difference_hours, 0.08, places=2)

    def test_absence(self):
        """A scheduled day with no attendance owes the whole day."""
        line = self._by_date(self._sheet())["2025-01-08"]
        self.assertEqual(line.status, "absent")
        self.assertEqual(line.check_in, 0.0)
        self.assertAlmostEqual(line.expected_hours, 8.0, places=2)
        self.assertAlmostEqual(line.worked_hours, 0.0, places=2)
        self.assertAlmostEqual(line.difference_hours, -8.0, places=2)

    def test_never_checked_out(self):
        """An attendance still open is its own status, not an absence."""
        line = self._by_date(self._sheet())["2025-01-09"]
        self.assertEqual(line.status, "open")
        self.assertEqual(line.check_in, 8.0)
        self.assertEqual(line.check_out, 0.0)
        # Nobody left early: we do not know when they left.
        self.assertEqual(line.early_minutes, 0.0)

    # -- the grace period, which is the part that cries wolf --------------

    def test_inside_the_grace_is_not_late(self):
        """08:08 with ten minutes of grace is on time."""
        line = self._by_date(self._sheet())["2025-01-10"]
        self.assertEqual(line.status, "ok")
        self.assertEqual(line.late_minutes, 0.0)

    def test_without_grace_the_same_day_is_late(self):
        """The same 08:08, with the grace set to zero, is eight minutes late."""
        line = self._by_date(self._sheet(grace_minutes=0))["2025-01-10"]
        self.assertEqual(line.status, "late")
        self.assertAlmostEqual(line.late_minutes, 8.0, places=1)

    # -- the totals -------------------------------------------------------

    def test_summary_counts(self):
        sheet = self._sheet()
        self.assertEqual(len(sheet.summary_ids), 1)
        summary = sheet.summary_ids
        self.assertEqual(summary.working_days, 5)
        self.assertEqual(summary.days_absent, 1)
        self.assertEqual(summary.days_present, 4)
        self.assertEqual(summary.days_late, 1)
        self.assertEqual(summary.days_early, 1)
        self.assertEqual(summary.days_open, 1)

    def test_summary_hours(self):
        """5 x 8 = 40 expected. Worked 9 + 8h05m + 0 + 0 + 8h52m = 25.95."""
        summary = self._sheet().summary_ids
        self.assertAlmostEqual(summary.expected_hours, 40.0, places=2)
        self.assertAlmostEqual(summary.worked_hours, 25.95, places=2)
        self.assertAlmostEqual(summary.difference_hours, -14.05, places=2)
        self.assertAlmostEqual(summary.late_minutes, 25.0, places=1)
        self.assertAlmostEqual(summary.early_minutes, 30.0, places=1)

    # -- the options ------------------------------------------------------

    def test_showing_non_working_days(self):
        """Unticking the skip adds the weekend back, with nothing expected."""
        sheet = self._sheet(skip_days_off=False)
        self.assertEqual(len(sheet.line_ids), 7)
        saturday = self._by_date(sheet)["2025-01-11"]
        self.assertEqual(saturday.expected_hours, 0.0)
        self.assertEqual(saturday.status, "absent")

    def test_dates_the_wrong_way_round_are_refused(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self._sheet(date_from="2025-01-12", date_to="2025-01-06")


@tagged("post_install", "-at_install")
class TestAttendanceSheetLunch(TransactionCase):
    """A calendar with an explicit lunch line, which is what Odoo ships.

    Odoo takes the lunch out of the worked hours of an attendance. If the
    expected hours kept it in, every employee would appear to owe an hour
    a day forever.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "MNA Test with lunch",
            "tz": "UTC",
            "hours_per_day": 8.0,
            "attendance_ids": [(5, 0, 0)] + [
                (0, 0, {"name": "%s %s" % (day, part), "dayofweek": str(day),
                        "hour_from": hour_from, "hour_to": hour_to, "day_period": part})
                for day in range(0, 5)
                for part, hour_from, hour_to in (
                    ("morning", 8.0, 12.0),
                    ("lunch", 12.0, 13.0),
                    ("afternoon", 13.0, 17.0),
                )
            ],
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Maya Haddad", "tz": "UTC", "resource_calendar_id": cls.calendar.id,
        })
        cls.env["hr.attendance"].create({
            "employee_id": cls.employee.id,
            "check_in": datetime(2025, 1, 6, 8, 0, 0),
            "check_out": datetime(2025, 1, 6, 17, 0, 0),
        })

    def test_the_lunch_hour_is_not_expected_work(self):
        """08:00 to 17:00 is eight worked hours against eight expected,
        so the day is square, not an hour short."""
        sheet = self.env["mna.attendance.sheet"].create({
            "date_from": "2025-01-06",
            "date_to": "2025-01-06",
            "employee_ids": [(6, 0, self.employee.ids)],
        })
        sheet.action_compute()
        line = sheet.line_ids
        self.assertEqual(line.planned_from, 8.0)
        self.assertEqual(line.planned_to, 17.0)
        self.assertAlmostEqual(line.expected_hours, 8.0, places=2)
        self.assertAlmostEqual(line.worked_hours, 8.0, places=2)
        self.assertAlmostEqual(line.difference_hours, 0.0, places=2)
        self.assertEqual(line.status, "ok")
