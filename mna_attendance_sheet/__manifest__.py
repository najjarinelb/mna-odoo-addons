{
    "name": "Monthly Attendance Sheet & Late/Early Report",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Attendances",
    "summary": "Who came late, who left early, who did not come at all, day by day against the working schedule",
    "description": """
Monthly Attendance Sheet & Late/Early Report
============================================

Odoo records attendances and totals the hours. What it does not do is put
the day the employee worked next to the day the employee was supposed to
work. That comparison is the whole of an attendance sheet, and without it
an HR officer exports to a spreadsheet every month.

What you get
------------
* One row per employee per working day: planned in and out, first check in,
  last check out, expected hours, worked hours, and the difference
* Late arrival and early leaving in minutes, measured against the
  employee's own working schedule, not a company wide guess
* A grace period you set, because a report that flags every two minute
  delay is a report nobody reads twice
* Absences: a scheduled day with no attendance at all
* Days where somebody forgot to check out, which otherwise quietly
  corrupt every hours total in the system
* A per employee summary with days present, absent, late and early, and
  the hours owed or over
* Filter, group and pivot on the detail, and export it

Written carefully
-----------------
* Times are read in each employee's own timezone, so a sheet for a team
  spread over three countries is still right
* Split shifts read as one span, and the expected hours exclude the break
  between them
* Non-working days are skipped by default, and can be shown if you want to
  see work recorded outside the schedule
* Read only. It reports, it never edits an attendance.

Works on Odoo 18 and 19, Community and Enterprise. Free and open source,
LGPL-3.
""",
    "author": "Mohammad Najjarine",
    "maintainer": "Mohammad Najjarine",
    "website": "https://github.com/najjarinelb",
    "license": "LGPL-3",
    "depends": ["hr_attendance"],
    "data": [
        "security/ir.model.access.csv",
        "views/mna_attendance_sheet_views.xml",
    ],
    "images": [
        "static/description/banner.png",
        "static/description/01_summary.png",
        "static/description/02_detail.png",
    ],
    "installable": True,
    "application": False,
}
