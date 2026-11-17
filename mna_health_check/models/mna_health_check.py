import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

OK, WARN, PROBLEM = "ok", "warning", "problem"


class MnaHealthCheck(models.TransientModel):
    _name = "mna.health.check"
    _description = "Odoo Health Check"

    date = fields.Datetime(readonly=True, default=fields.Datetime.now)
    line_ids = fields.One2many("mna.health.check.line", "check_id", readonly=True)
    problem_count = fields.Integer(compute="_compute_counts")
    warning_count = fields.Integer(compute="_compute_counts")
    database = fields.Char(readonly=True)
    db_size = fields.Char(string="Database Size", readonly=True)

    @api.depends("line_ids.status")
    def _compute_counts(self):
        for check in self:
            statuses = check.line_ids.mapped("status")
            check.problem_count = statuses.count(PROBLEM)
            check.warning_count = statuses.count(WARN)

    # ------------------------------------------------------------------
    # Running the checks
    # ------------------------------------------------------------------
    @api.model
    def action_run(self):
        """Create a fresh report and open it."""
        check = self.create({})
        check._run()
        return {
            "type": "ir.actions.act_window",
            "name": _("Health Check"),
            "res_model": "mna.health.check",
            "res_id": check.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_refresh(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.date = fields.Datetime.now()
        self._run()
        return True

    def _run(self):
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only a settings administrator can run the health check."))
        self.database = self.env.cr.dbname
        self.db_size = self._database_size()
        values = []
        for method in (
            self._check_crons,
            self._check_failed_mail,
            self._check_queued_mail,
            self._check_db_attachments,
            self._check_big_tables,
            self._check_ghost_modules,
            self._check_admin_users,
            self._check_never_logged_in,
        ):
            try:
                result = method()
            except Exception as exc:  # noqa: BLE001 - one broken check must not hide the rest
                _logger.exception("Health check %s failed", method.__name__)
                result = {
                    "name": method.__name__.replace("_check_", "").replace("_", " ").title(),
                    "status": WARN,
                    "detail": _("This check could not run: %s", exc),
                }
            if result:
                result["check_id"] = self.id
                values.append(result)
        self.env["mna.health.check.line"].create(values)

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------
    def _database_size(self):
        self.env.cr.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        return self.env.cr.fetchone()[0]

    def _check_crons(self):
        crons = self.env["ir.cron"].sudo().search([])
        stopped = crons.filtered(lambda c: not c.active)
        overdue = crons.filtered(
            lambda c: c.active and c.nextcall and c.nextcall < fields.Datetime.now()
        )
        if overdue:
            status, detail = PROBLEM, _(
                "%(n)s active scheduled action(s) are past their next run time. "
                "The cron worker may not be running.", n=len(overdue)
            )
            records = overdue
        elif stopped:
            status, detail = WARN, _(
                "%(n)s scheduled action(s) are switched off.", n=len(stopped)
            )
            records = stopped
        else:
            status, detail = OK, _("All %s scheduled actions are active and on time.", len(crons))
            records = crons
        return {
            "name": _("Scheduled Actions"),
            "status": status,
            "count": len(records),
            "detail": detail,
            "res_model": "ir.cron",
            "res_ids": repr(records.ids),
        }

    def _check_failed_mail(self):
        failed = self.env["mail.mail"].sudo().search([("state", "=", "exception")])
        return {
            "name": _("Failed Emails"),
            "status": PROBLEM if failed else OK,
            "count": len(failed),
            "detail": _("%s outgoing email(s) failed to send.", len(failed))
            if failed
            else _("No failed outgoing emails."),
            "res_model": "mail.mail",
            "res_ids": repr(failed.ids),
        }

    def _check_queued_mail(self):
        queued = self.env["mail.mail"].sudo().search([("state", "=", "outgoing")])
        stale = queued.filtered(
            lambda m: m.create_date
            and (fields.Datetime.now() - m.create_date).days >= 1
        )
        if stale:
            status = PROBLEM
            detail = _(
                "%(n)s email(s) have been waiting in the queue for over a day. "
                "Check the outgoing mail server and the Email Queue Manager action.",
                n=len(stale),
            )
        elif queued:
            status, detail = WARN, _("%s email(s) waiting to be sent.", len(queued))
        else:
            status, detail = OK, _("The outgoing mail queue is empty.")
        return {
            "name": _("Outgoing Mail Queue"),
            "status": status,
            "count": len(stale or queued),
            "detail": detail,
            "res_model": "mail.mail",
            "res_ids": repr((stale or queued).ids),
        }

    def _check_db_attachments(self):
        self.env.cr.execute("""
            SELECT count(*), COALESCE(sum(file_size), 0)
            FROM ir_attachment
            WHERE db_datas IS NOT NULL
        """)
        count, size = self.env.cr.fetchone()
        mb = (size or 0) / 1048576.0
        if mb > 500:
            status = PROBLEM
            detail = _(
                "%(n)s attachment(s) totalling %(mb).0f MB are stored inside the database "
                "rather than on disk. This makes every backup that much larger.",
                n=count, mb=mb,
            )
        elif count:
            status = WARN
            detail = _(
                "%(n)s attachment(s) totalling %(mb).1f MB are stored inside the database.",
                n=count, mb=mb,
            )
        else:
            status, detail = OK, _("All attachments are stored on the filestore.")
        return {
            "name": _("Attachments In Database"),
            "status": status,
            "count": count,
            "detail": detail,
        }

    def _check_big_tables(self):
        self.env.cr.execute("""
            SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid)) AS pretty,
                   pg_total_relation_size(c.oid) AS bytes
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = 'public'
            ORDER BY bytes DESC
            LIMIT 10
        """)
        rows = self.env.cr.fetchall()
        detail = "\n".join("%s: %s" % (name, pretty) for name, pretty, _b in rows)
        return {
            "name": _("Largest Tables"),
            "status": OK,
            "count": len(rows),
            "detail": detail or _("No tables found."),
        }

    def _check_ghost_modules(self):
        installed = self.env["ir.module.module"].sudo().search([("state", "=", "installed")])
        ghosts = installed.filtered(lambda m: not m.shortdesc and not m.author)
        return {
            "name": _("Installed Modules"),
            "status": WARN if ghosts else OK,
            "count": len(ghosts) or len(installed),
            "detail": _(
                "%s installed module(s) have no manifest information, which usually means "
                "their folder is missing from the addons path.", len(ghosts)
            )
            if ghosts
            else _("%s modules installed, all present in the addons path.", len(installed)),
            "res_model": "ir.module.module",
            "res_ids": repr(ghosts.ids),
        }

    def _check_admin_users(self):
        admins = self.env["res.users"].sudo().search(
            [("active", "=", True), ("groups_id", "in", self.env.ref("base.group_system").id)]
        )
        internal = admins.filtered(lambda u: not u.share)
        return {
            "name": _("Administrators"),
            "status": WARN if len(internal) > 3 else OK,
            "count": len(internal),
            "detail": _(
                "%s users have full settings access. Worth reviewing whether they all still need it.",
                len(internal),
            )
            if len(internal) > 3
            else _("%s user(s) have full settings access.", len(internal)),
            "res_model": "res.users",
            "res_ids": repr(internal.ids),
        }

    def _check_never_logged_in(self):
        users = self.env["res.users"].sudo().search(
            [("active", "=", True), ("share", "=", False), ("login_date", "=", False)]
        )
        return {
            "name": _("Users Who Never Logged In"),
            "status": WARN if users else OK,
            "count": len(users),
            "detail": _(
                "%s active internal user(s) have never logged in. Each one may still be "
                "consuming a subscription seat.", len(users)
            )
            if users
            else _("Every active internal user has logged in at least once."),
            "res_model": "res.users",
            "res_ids": repr(users.ids),
        }


class MnaHealthCheckLine(models.TransientModel):
    _name = "mna.health.check.line"
    _description = "Odoo Health Check Result"
    _order = "sequence, id"

    check_id = fields.Many2one("mna.health.check", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    status = fields.Selection(
        [(OK, "OK"), (WARN, "Warning"), (PROBLEM, "Problem")], required=True, default=OK
    )
    count = fields.Integer()
    detail = fields.Text()
    res_model = fields.Char()
    res_ids = fields.Char()

    def action_open_records(self):
        self.ensure_one()
        if not self.res_model or not self.res_ids:
            return False
        try:
            ids = [int(i) for i in self.res_ids.strip("[]").split(",") if i.strip()]
        except ValueError:
            return False
        if not ids:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": self.res_model,
            "view_mode": "list,form",
            "domain": [("id", "in", ids)],
            "target": "current",
        }
