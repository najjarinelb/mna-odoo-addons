import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

OK, WARN, PROBLEM = "ok", "warning", "problem"

# A session left open is not automatically wrong: a shop that trades past
# midnight has one open every morning. What matters is how long, so the
# checks are written around thresholds a shop owner can change rather
# than around absolutes that would cry wolf every day.
DEFAULT_OPEN_DAYS = 2
DEFAULT_DIFFERENCE = 5.0


class MnaPosCheck(models.Model):
    _name = "mna.pos.check"
    _description = "POS Session Check"
    _order = "date desc, id desc"

    date = fields.Datetime(readonly=True, default=fields.Datetime.now)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, readonly=True
    )
    config_ids = fields.Many2many(
        "pos.config", string="Points of Sale",
        help="Leave empty to check every point of sale.",
    )
    days = fields.Integer(
        string="Look Back (days)", default=30,
        help="Sessions closed within this many days are examined.",
    )
    max_open_days = fields.Integer(
        string="Open Session Limit (days)", default=DEFAULT_OPEN_DAYS,
        help="A session still open for longer than this is reported.",
    )
    difference_threshold = fields.Float(
        string="Cash Difference Threshold", default=DEFAULT_DIFFERENCE,
        help="Closing differences smaller than this are treated as noise.",
    )

    line_ids = fields.One2many("mna.pos.check.line", "check_id", readonly=True)
    problem_count = fields.Integer(compute="_compute_counts")
    warning_count = fields.Integer(compute="_compute_counts")
    session_count = fields.Integer(readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    total_difference = fields.Monetary(
        readonly=True, currency_field="currency_id",
        help="Net of all closing differences in the period. A number close to "
             "zero made of large offsetting differences is still worth a look.",
    )
    absolute_difference = fields.Monetary(
        readonly=True, currency_field="currency_id",
        help="The same differences added without their signs, which is the "
             "figure that says how much cash went astray in total.",
    )

    def _compute_counts(self):
        for check in self:
            statuses = check.line_ids.mapped("status")
            check.problem_count = statuses.count(PROBLEM)
            check.warning_count = statuses.count(WARN)

    @api.depends("date")
    def _compute_display_name(self):
        for check in self:
            check.display_name = _("POS Check")

    # ------------------------------------------------------------------
    @api.model
    def action_run(self):
        check = self.create({})
        check._run()
        return {
            "type": "ir.actions.act_window",
            "name": _("POS Session Check"),
            "res_model": "mna.pos.check",
            "res_id": check.id,
            "view_mode": "form",
        }

    def action_refresh(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.date = fields.Datetime.now()
        self._run()
        return True

    def _run(self):
        self.ensure_one()
        if not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Only a Point of Sale manager can run this check."))
        values = []
        for method in (
            self._check_open_too_long,
            self._check_cash_differences,
            self._check_repeat_offenders,
            self._check_unpaid_orders,
            self._check_uninvoiced_to_invoice,
            self._check_unposted_sessions,
            self._check_rounding_mismatch,
            self._check_negative_lines,
        ):
            try:
                result = method()
            except Exception as exc:  # noqa: BLE001 - one broken check must not hide the rest
                _logger.exception("POS check %s failed", method.__name__)
                result = {
                    "name": method.__name__.replace("_check_", "").replace("_", " ").title(),
                    "status": WARN,
                    "detail": _("This check could not run: %s", exc),
                }
            if result:
                result["check_id"] = self.id
                values.append(result)
        self.env["mna.pos.check.line"].create(values)
        self._compute_totals()

    # ------------------------------------------------------------------
    def _session_domain(self, closed_only=True):
        domain = [("company_id", "=", self.company_id.id)]
        if self.config_ids:
            domain.append(("config_id", "in", self.config_ids.ids))
        if closed_only:
            since = fields.Datetime.subtract(fields.Datetime.now(), days=self.days or 30)
            domain += [("state", "=", "closed"), ("stop_at", ">=", since)]
        return domain

    def _sessions(self):
        return self.env["pos.session"].search(self._session_domain())

    def _compute_totals(self):
        sessions = self._sessions()
        differences = sessions.mapped("cash_register_difference")
        self.session_count = len(sessions)
        self.total_difference = sum(differences)
        self.absolute_difference = sum(abs(d) for d in differences)

    def _line(self, name, status, count=0, detail="", records=None, sequence=10):
        values = {
            "name": name, "status": status, "count": count,
            "detail": detail, "sequence": sequence,
        }
        if records:
            values["res_model"] = records._name
            values["res_ids"] = repr(records.ids)
        return values

    # ------------------------------------------------------------------
    # The checks
    # ------------------------------------------------------------------
    def _check_open_too_long(self):
        limit = fields.Datetime.subtract(
            fields.Datetime.now(), days=self.max_open_days or DEFAULT_OPEN_DAYS
        )
        sessions = self.env["pos.session"].search(
            self._session_domain(closed_only=False)
            + [("state", "!=", "closed"), ("start_at", "<", limit)]
        )
        if not sessions:
            return self._line(
                _("Sessions left open"), OK,
                detail=_("No session has been open longer than %s days.",
                         self.max_open_days or DEFAULT_OPEN_DAYS),
                sequence=10,
            )
        oldest = min(sessions.mapped("start_at"))
        days = (fields.Datetime.now() - oldest).days
        return self._line(
            _("Sessions left open"), PROBLEM, len(sessions),
            _("%(count)s session(s) still open, the oldest for %(days)s days. "
              "An open session holds its orders out of your accounts, so the "
              "takings are not in the ledger yet.",
              count=len(sessions), days=days),
            sessions, sequence=10,
        )

    def _check_cash_differences(self):
        sessions = self._sessions()
        threshold = self.difference_threshold or DEFAULT_DIFFERENCE
        rounding = self.currency_id.rounding
        flagged = sessions.filtered(
            lambda s: float_compare(
                abs(s.cash_register_difference), threshold, precision_rounding=rounding
            ) > 0
        )
        if not flagged:
            return self._line(
                _("Cash closing differences"), OK,
                detail=_("No session closed more than %s out.",
                         self.currency_id.format(threshold)),
                sequence=20,
            )
        worst = max(flagged, key=lambda s: abs(s.cash_register_difference))
        status = PROBLEM if len(flagged) > len(sessions) * 0.2 else WARN
        return self._line(
            _("Cash closing differences"), status, len(flagged),
            _("%(count)s of %(total)s sessions closed more than %(threshold)s out. "
              "The largest was %(worst)s on %(name)s.",
              count=len(flagged), total=len(sessions),
              threshold=self.currency_id.format(threshold),
              worst=self.currency_id.format(worst.cash_register_difference),
              name=worst.name),
            flagged, sequence=20,
        )

    def _check_repeat_offenders(self):
        """One bad night is an accident. The same person every week is not.

        This is the check a shop owner actually wants and no report gives
        them: not which session was short, but whether the shortfalls
        follow a person.
        """
        sessions = self._sessions()
        threshold = self.difference_threshold or DEFAULT_DIFFERENCE
        by_user = {}
        for session in sessions:
            if abs(session.cash_register_difference) <= threshold:
                continue
            entry = by_user.setdefault(session.user_id, {"count": 0, "total": 0.0})
            entry["count"] += 1
            entry["total"] += session.cash_register_difference
        repeat = {u: v for u, v in by_user.items() if v["count"] >= 3}
        if not repeat:
            return self._line(
                _("Differences following one person"), OK,
                detail=_("No one has closed short or over three or more times."),
                sequence=30,
            )
        worst = sorted(repeat.items(), key=lambda kv: abs(kv[1]["total"]), reverse=True)
        detail = "\n".join(
            _("%(user)s: %(count)s sessions, %(total)s net",
              user=user.display_name, count=data["count"],
              total=self.currency_id.format(data["total"]))
            for user, data in worst
        )
        return self._line(
            _("Differences following one person"), WARN, len(repeat),
            detail + "\n\n" + _(
                "Counting three or more sessions outside the threshold. This is "
                "worth a conversation before it is worth an accusation: a till "
                "shared between people, or a float never reset, looks the same."
            ),
            sequence=30,
        )

    def _check_unpaid_orders(self):
        orders = self.env["pos.order"].search([
            ("company_id", "=", self.company_id.id),
            ("session_id", "in", self._sessions().ids),
            ("state", "in", ("draft", "cancel")),
        ])
        if not orders:
            return self._line(
                _("Orders left unpaid"), OK,
                detail=_("Every order in these sessions was paid or refunded."),
                sequence=40,
            )
        return self._line(
            _("Orders left unpaid"), WARN, len(orders),
            _("%s order(s) in closed sessions are still draft or cancelled.",
              len(orders)),
            orders, sequence=40,
        )

    def _check_uninvoiced_to_invoice(self):
        """Orders a customer asked to be invoiced, that never were."""
        orders = self.env["pos.order"].search([
            ("company_id", "=", self.company_id.id),
            ("session_id", "in", self._sessions().ids),
            ("to_invoice", "=", True),
            ("account_move", "=", False),
            ("state", "!=", "cancel"),
        ])
        if not orders:
            return self._line(
                _("Invoices never issued"), OK,
                detail=_("Every order marked for invoicing has an invoice."),
                sequence=50,
            )
        return self._line(
            _("Invoices never issued"), PROBLEM, len(orders),
            _("%s order(s) were marked to invoice but have no invoice. The "
              "customer is still waiting for a document you have already "
              "taken the money for.", len(orders)),
            orders, sequence=50,
        )

    def _check_unposted_sessions(self):
        sessions = self._sessions().filtered(
            lambda s: s.move_id and s.move_id.state == "draft"
        )
        if not sessions:
            return self._line(
                _("Session entries not posted"), OK,
                detail=_("Every closed session posted its journal entry."),
                sequence=60,
            )
        return self._line(
            _("Session entries not posted"), PROBLEM, len(sessions),
            _("%s closed session(s) left their journal entry in draft, so the "
              "sales are not in your accounts.", len(sessions)),
            sessions, sequence=60,
        )

    def _check_rounding_mismatch(self):
        """Orders where what was paid does not match what was charged."""
        rounding = self.currency_id.rounding
        orders = self.env["pos.order"].search([
            ("company_id", "=", self.company_id.id),
            ("session_id", "in", self._sessions().ids),
            ("state", "in", ("paid", "done", "invoiced")),
        ])
        mismatched = orders.filtered(
            lambda o: not float_is_zero(
                o.amount_total - o.amount_paid, precision_rounding=rounding
            )
        )
        if not mismatched:
            return self._line(
                _("Paid matches charged"), OK,
                detail=_("Every settled order was paid in full."),
                sequence=70,
            )
        total = sum(o.amount_total - o.amount_paid for o in mismatched)
        return self._line(
            _("Paid does not match charged"), WARN, len(mismatched),
            _("%(count)s order(s) where paid and total differ, %(total)s in all. "
              "Cash rounding explains small amounts; anything larger does not.",
              count=len(mismatched), total=self.currency_id.format(total)),
            mismatched, sequence=70,
        )

    def _check_negative_lines(self):
        """Negative lines outside a proper refund, which is how shrinkage hides."""
        lines = self.env["pos.order.line"].search([
            ("company_id", "=", self.company_id.id),
            ("order_id.session_id", "in", self._sessions().ids),
            ("qty", "<", 0),
            ("refunded_orderline_id", "=", False),
        ])
        if not lines:
            return self._line(
                _("Negative lines outside refunds"), OK,
                detail=_("Every negative line belongs to a refund of a real order."),
                sequence=80,
            )
        orders = lines.mapped("order_id")
        return self._line(
            _("Negative lines outside refunds"), WARN, len(lines),
            _("%(lines)s negative line(s) across %(orders)s order(s) are not linked "
              "to the order they refund. These are hand typed negatives, which is "
              "how a discount nobody approved gets recorded.",
              lines=len(lines), orders=len(orders)),
            orders, sequence=80,
        )


class MnaPosCheckLine(models.Model):
    _name = "mna.pos.check.line"
    _description = "POS Session Check Result"
    _order = "sequence, id"

    check_id = fields.Many2one("mna.pos.check", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    status = fields.Selection(
        [(OK, "OK"), (WARN, "Warning"), (PROBLEM, "Problem")], required=True
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
        }
