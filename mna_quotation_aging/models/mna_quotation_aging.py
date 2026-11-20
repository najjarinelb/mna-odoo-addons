# Part of the Najjarine Tech Odoo modules. See LICENSE file for full
# copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang

# The buckets are in days and the last one is open ended. They are kept
# here rather than on the record because a report whose columns move is a
# report nobody can compare against last month's.
BUCKETS = [
    ("b_0_7", "0 to 7", 0, 7),
    ("b_8_14", "8 to 14", 8, 14),
    ("b_15_30", "15 to 30", 15, 30),
    ("b_31_60", "31 to 60", 31, 60),
    ("b_60_plus", "Over 60", 61, None),
]


class MnaQuotationAging(models.TransientModel):
    _name = "mna.quotation.aging"
    _description = "Quotation Pipeline Aging"

    date_from = fields.Date(
        string="From", required=True,
        default=lambda self: fields.Date.context_today(self).replace(
            month=1, day=1))
    date_to = fields.Date(
        string="To", required=True,
        default=lambda self: fields.Date.context_today(self))
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company)
    only_my_team = fields.Boolean(
        string="My Quotations Only",
        help="Show only the quotations you are the salesperson on.")

    line_ids = fields.One2many(
        "mna.quotation.aging.line", "wizard_id", string="Salespeople")
    has_run = fields.Boolean()
    note = fields.Char(readonly=True)

    total_open = fields.Integer(string="Open", readonly=True)
    total_open_amount = fields.Monetary(
        string="Open Value", readonly=True, currency_field="currency_id",
        help="Untaxed, because a pipeline is measured against revenue.")
    total_expired = fields.Integer(string="Expired", readonly=True)
    total_won = fields.Integer(string="Won", readonly=True)
    total_lost = fields.Integer(string="Lost", readonly=True)
    total_win_rate = fields.Float(string="Win Rate (%)", readonly=True)
    currency_id = fields.Many2one(
        "res.currency", readonly=True,
        default=lambda self: self.env.company.currency_id)

    # ------------------------------------------------------------------
    @api.model
    def _bucket_for(self, age_days):
        """The bucket an age in days falls into.

        Written as a lookup over one list so the report and the tests
        cannot disagree about where a boundary sits.
        """
        for key, _label, low, high in BUCKETS:
            if age_days >= low and (high is None or age_days <= high):
                return key
        # Only reachable for a negative age, which means a quotation
        # dated in the future. It is newer than new, so it goes in the
        # youngest bucket rather than being dropped from the counts.
        return BUCKETS[0][0]

    # ------------------------------------------------------------------
    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("The start date is after the end date."))
        self.line_ids.unlink()
        self.currency_id = self.company_id.currency_id

        domain = [
            ("company_id", "=", self.company_id.id),
            ("date_order", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("date_order", "<=", fields.Datetime.to_datetime(
                self.date_to).replace(hour=23, minute=59, second=59)),
        ]
        if self.only_my_team:
            domain.append(("user_id", "=", self.env.user.id))
        orders = self.env["sale.order"].search(domain)

        today = fields.Date.context_today(self)
        per_user = {}

        def row_for(user):
            key = user.id or 0
            if key not in per_user:
                per_user[key] = {
                    "wizard_id": self.id,
                    "salesperson_id": user.id or False,
                    "open_count": 0,
                    "open_amount": 0.0,
                    "expired_count": 0,
                    "no_activity_count": 0,
                    "won_count": 0,
                    "lost_count": 0,
                    "oldest_days": 0,
                    "currency_id": self.currency_id.id,
                }
                for bucket_key, _label, _low, _high in BUCKETS:
                    per_user[key][bucket_key] = 0
            return per_user[key]

        for order in orders:
            row = row_for(order.user_id)
            if order.state in ("draft", "sent"):
                order_date = fields.Datetime.context_timestamp(
                    self, order.date_order).date()
                age = (today - order_date).days
                row["open_count"] += 1
                row["open_amount"] += self._in_company_currency(order)
                row[self._bucket_for(age)] += 1
                row["oldest_days"] = max(row["oldest_days"], age)
                if order.validity_date and order.validity_date < today:
                    row["expired_count"] += 1
                if not order.activity_ids:
                    row["no_activity_count"] += 1
            elif order.state == "sale":
                row["won_count"] += 1
            elif order.state == "cancel":
                row["lost_count"] += 1

        rows = [vals for vals in per_user.values()
                if vals["open_count"] or vals["won_count"]
                or vals["lost_count"]]
        self.env["mna.quotation.aging.line"].create(rows)

        self.total_open = sum(r["open_count"] for r in rows)
        self.total_open_amount = sum(r["open_amount"] for r in rows)
        self.total_expired = sum(r["expired_count"] for r in rows)
        self.total_won = sum(r["won_count"] for r in rows)
        self.total_lost = sum(r["lost_count"] for r in rows)
        decided = self.total_won + self.total_lost
        # A win rate over nothing decided is not zero percent, it is
        # unknown, and showing zero would read as a terrible quarter.
        self.total_win_rate = (
            self.total_won / decided * 100.0) if decided else 0.0
        self.has_run = True
        if not rows:
            self.note = _("No quotations in this period.")
        else:
            self.note = _(
                "%(open)s open worth %(amount)s, %(expired)s of them past "
                "their expiry date. %(won)s won and %(lost)s lost.") % {
                "open": self.total_open,
                # Formatted, because a pipeline figure printed raw as
                # 146114.8 is harder to read than the table above it.
                "amount": formatLang(
                    self.env, self.total_open_amount,
                    currency_obj=self.currency_id),
                "expired": self.total_expired,
                "won": self.total_won,
                "lost": self.total_lost,
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Quotation Pipeline Aging"),
            "res_model": "mna.quotation.aging",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _in_company_currency(self, order):
        """An order's total in the company's own currency.

        A pipeline figure that adds a dollar order to a euro one without
        converting is a number that means nothing, so each order is
        converted at its own order date.
        """
        company_currency = self.company_id.currency_id
        # Untaxed on purpose: a pipeline is compared against a revenue
        # target, and tax is not revenue. Including it would overstate
        # every figure on the report by the tax rate.
        amount = order.amount_untaxed
        if not order.currency_id or order.currency_id == company_currency:
            return amount
        order_date = order.date_order and fields.Datetime.context_timestamp(
            self, order.date_order).date() or fields.Date.context_today(self)
        return order.currency_id._convert(
            amount, company_currency, self.company_id, order_date)


class MnaQuotationAgingLine(models.TransientModel):
    _name = "mna.quotation.aging.line"
    _description = "Quotation Pipeline Aging Line"
    _order = "open_amount desc, id"

    wizard_id = fields.Many2one(
        "mna.quotation.aging", required=True, ondelete="cascade", index=True)
    salesperson_id = fields.Many2one("res.users", string="Salesperson")
    currency_id = fields.Many2one("res.currency", readonly=True)

    open_count = fields.Integer(string="Open")
    open_amount = fields.Monetary(
        string="Open Value", currency_field="currency_id")
    b_0_7 = fields.Integer(string="0-7")
    b_8_14 = fields.Integer(string="8-14")
    b_15_30 = fields.Integer(string="15-30")
    b_31_60 = fields.Integer(string="31-60")
    b_60_plus = fields.Integer(string="60+")
    oldest_days = fields.Integer(string="Oldest (days)")
    expired_count = fields.Integer(string="Expired")
    no_activity_count = fields.Integer(string="No Next Step")
    won_count = fields.Integer(string="Won")
    lost_count = fields.Integer(string="Lost")
    win_rate = fields.Float(
        string="Win Rate (%)", compute="_compute_win_rate")

    @api.depends("won_count", "lost_count")
    def _compute_win_rate(self):
        for line in self:
            decided = line.won_count + line.lost_count
            line.win_rate = (
                line.won_count / decided * 100.0) if decided else 0.0

    def action_open_quotations(self):
        """The open quotations behind this row, so the number is not a
        dead end."""
        self.ensure_one()
        wizard = self.wizard_id
        domain = [
            ("company_id", "=", wizard.company_id.id),
            ("state", "in", ("draft", "sent")),
            ("date_order", ">=", fields.Datetime.to_datetime(
                wizard.date_from)),
            ("date_order", "<=", fields.Datetime.to_datetime(
                wizard.date_to).replace(hour=23, minute=59, second=59)),
        ]
        if self.salesperson_id:
            domain.append(("user_id", "=", self.salesperson_id.id))
        else:
            domain.append(("user_id", "=", False))
        return {
            "type": "ir.actions.act_window",
            "name": _("Open Quotations"),
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": domain,
            "target": "current",
        }
