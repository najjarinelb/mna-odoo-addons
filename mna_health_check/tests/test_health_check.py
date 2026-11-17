from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHealthCheck(TransactionCase):
    def _run(self):
        check = self.env["mna.health.check"].create({})
        check._run()
        return check

    def _line(self, check, name):
        return check.line_ids.filtered(lambda l: l.name == name)

    def test_runs_and_reports_every_check(self):
        check = self._run()
        self.assertEqual(len(check.line_ids), 8)
        self.assertTrue(check.db_size)
        self.assertEqual(check.database, self.env.cr.dbname)
        for line in check.line_ids:
            self.assertIn(line.status, ("ok", "warning", "problem"))
            self.assertTrue(line.detail)
            # A check that crashed reports itself this way; none should.
            self.assertNotIn("could not run", line.detail)

    def test_failed_email_is_flagged(self):
        # Count what is already there: the database under test may not be clean.
        before = self._line(self._run(), "Failed Emails").count
        self.env["mail.mail"].create({"subject": "Broken", "state": "exception"})
        failed = self._line(self._run(), "Failed Emails")
        self.assertEqual(failed.status, "problem")
        self.assertEqual(failed.count, before + 1)
        action = failed.action_open_records()
        self.assertEqual(action["res_model"], "mail.mail")

    def test_stale_queue_is_flagged(self):
        mail = self.env["mail.mail"].create({"subject": "Waiting", "state": "outgoing"})
        self.env.cr.execute(
            "UPDATE mail_mail SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=3), mail.id),
        )
        mail.invalidate_recordset()
        line = self._line(self._run(), "Outgoing Mail Queue")
        self.assertEqual(line.status, "problem")

    def test_overdue_cron_is_flagged(self):
        cron = self.env["ir.cron"].search([("active", "=", True)], limit=1)
        if not cron:
            self.skipTest("No active scheduled action in this database")
        cron.nextcall = fields.Datetime.now() - timedelta(days=2)
        line = self._line(self._run(), "Scheduled Actions")
        self.assertEqual(line.status, "problem")
        self.assertGreaterEqual(line.count, 1)

    def test_largest_tables_listed(self):
        line = self._line(self._run(), "Largest Tables")
        self.assertEqual(line.status, "ok")
        self.assertIn(":", line.detail)

    def test_requires_administrator(self):
        user = self.env["res.users"].create({
            "name": "Plain User", "login": "mna_plain", "email": "mna_plain@example.com",
        })
        # Access rules stop a non-administrator before the check even starts.
        with self.assertRaises(AccessError):
            self.env["mna.health.check"].with_user(user).create({})
        # And the guard inside _run holds even with the record handed to them.
        check = self.env["mna.health.check"].create({})
        with self.assertRaises(AccessError):
            check.with_user(user).sudo(False)._run()

    def test_open_records_handles_empty(self):
        line = self.env["mna.health.check.line"].create({
            "check_id": self.env["mna.health.check"].create({}).id,
            "name": "Nothing", "status": "ok",
        })
        self.assertFalse(line.action_open_records())
