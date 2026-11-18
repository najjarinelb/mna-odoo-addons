from odoo import _, api, fields, models
from odoo.exceptions import UserError

# An X report is a look at a till that is still trading: it can be taken
# as often as you like and changes nothing. A Z report closes the day. In
# a good many countries it is the document an inspector asks for, which
# is why this one is numbered in an unbroken sequence, cannot be taken
# twice for the same session, and keeps its figures rather than
# recomputing them on the way to the printer.
REPORT_TYPES = [("x", "X Report (during trade)"), ("z", "Z Report (end of day)")]

PAYMENT, TAX, CATEGORY = "payment", "tax", "category"


class MnaPosZReport(models.Model):
    _name = "mna.pos.zreport"
    _description = "POS X/Z Report"
    _order = "date_taken desc, id desc"
    _rec_name = "name"

    name = fields.Char(required=True, readonly=True, copy=False)
    report_type = fields.Selection(REPORT_TYPES, required=True, readonly=True)
    session_id = fields.Many2one(
        "pos.session", required=True, readonly=True, index=True, ondelete="restrict"
    )
    config_id = fields.Many2one(
        "pos.config", related="session_id.config_id", store=True, readonly=True
    )
    company_id = fields.Many2one(
        "res.company", related="session_id.company_id", store=True, readonly=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    cashier_id = fields.Many2one(
        "res.users", related="session_id.user_id", store=True, readonly=True,
        string="Session Opened By",
    )
    taken_by_id = fields.Many2one("res.users", readonly=True, string="Report Taken By")
    date_taken = fields.Datetime(readonly=True, required=True)
    session_start = fields.Datetime(readonly=True)
    session_stop = fields.Datetime(readonly=True)

    order_count = fields.Integer(readonly=True)
    refund_count = fields.Integer(readonly=True)
    item_count = fields.Float(readonly=True, string="Items Sold")
    gross_sales = fields.Monetary(
        readonly=True, currency_field="currency_id",
        help="Before discount and before tax: what the price list would have charged.",
    )
    discount_total = fields.Monetary(readonly=True, currency_field="currency_id")
    net_sales = fields.Monetary(
        readonly=True, currency_field="currency_id",
        help="After discount, before tax.",
    )
    tax_total = fields.Monetary(readonly=True, currency_field="currency_id")
    total_sales = fields.Monetary(
        readonly=True, currency_field="currency_id", string="Total Taken",
        help="What the customers paid, tax included.",
    )
    refund_total = fields.Monetary(readonly=True, currency_field="currency_id")
    average_basket = fields.Monetary(readonly=True, currency_field="currency_id")

    opening_float = fields.Monetary(readonly=True, currency_field="currency_id")
    cash_sales = fields.Monetary(readonly=True, currency_field="currency_id")
    cash_in = fields.Monetary(readonly=True, currency_field="currency_id")
    cash_out = fields.Monetary(readonly=True, currency_field="currency_id")
    expected_cash = fields.Monetary(
        readonly=True, currency_field="currency_id",
        help="Opening float, plus cash taken, plus money put in, less money taken out.",
    )
    counted_cash = fields.Monetary(readonly=True, currency_field="currency_id")
    cash_difference = fields.Monetary(readonly=True, currency_field="currency_id")

    line_ids = fields.One2many("mna.pos.zreport.line", "report_id", readonly=True)
    payment_line_ids = fields.One2many(
        "mna.pos.zreport.line", "report_id", domain=[("kind", "=", PAYMENT)],
        string="By Payment Method", readonly=True,
    )
    tax_line_ids = fields.One2many(
        "mna.pos.zreport.line", "report_id", domain=[("kind", "=", TAX)],
        string="By Tax", readonly=True,
    )
    category_line_ids = fields.One2many(
        "mna.pos.zreport.line", "report_id", domain=[("kind", "=", CATEGORY)],
        string="By Category", readonly=True,
    )

    note = fields.Text()

    _sql_constraints = [(
        "name_uniq", "unique(name, company_id)",
        "A report with this number already exists.",
    )]

    # ------------------------------------------------------------------
    @api.model
    def action_take_x(self, session_id=None):
        session = self._pick_session(session_id, require_open=True)
        return self._open(self._build(session, "x"))

    @api.model
    def action_take_z(self, session_id=None):
        session = self._pick_session(session_id, require_open=False)
        return self._open(self._build(session, "z"))

    def _pick_session(self, session_id, require_open):
        if session_id:
            session = self.env["pos.session"].browse(session_id).exists()
        elif require_open:
            session = self.env["pos.session"].search(
                [("state", "=", "opened"), ("company_id", "=", self.env.company.id)],
                order="start_at desc", limit=1,
            )
        else:
            session = self.env["pos.session"].search(
                [("state", "=", "closed"), ("company_id", "=", self.env.company.id)],
                order="stop_at desc", limit=1,
            )
        if not session:
            raise UserError(_(
                "No session to report on. An X report needs a session that is "
                "trading; a Z report needs one that has been closed."
            ))
        return session

    def _open(self, report):
        return {
            "type": "ir.actions.act_window",
            "res_model": "mna.pos.zreport",
            "res_id": report.id,
            "view_mode": "form",
        }

    @api.model
    def _build(self, session, report_type):
        if not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise UserError(_("Only a Point of Sale manager can take a report."))
        if report_type == "z":
            if session.state != "closed":
                raise UserError(_(
                    "A Z report closes the day, so the session has to be closed "
                    "first. Take an X report to see where the till stands now."
                ))
            existing = self.search([
                ("session_id", "=", session.id), ("report_type", "=", "z")
            ], limit=1)
            if existing:
                raise UserError(_(
                    "This session already has Z report %s. A Z report is taken "
                    "once and kept; print that one again rather than taking "
                    "another.", existing.name,
                ))
            name = self.env["ir.sequence"].next_by_code("mna.pos.zreport") or _("Z")
        else:
            # An X report changes nothing, so an older one for the same
            # session is replaced rather than piling up.
            self.search([
                ("session_id", "=", session.id), ("report_type", "=", "x")
            ]).unlink()
            name = _("X / %s", session.name)

        report = self.create({
            "name": name,
            "report_type": report_type,
            "session_id": session.id,
            "date_taken": fields.Datetime.now(),
            "taken_by_id": self.env.user.id,
            "session_start": session.start_at,
            "session_stop": session.stop_at,
        })
        report.with_context(mna_building_report=True)._collect(session)
        return report

    # ------------------------------------------------------------------
    def _collect(self, session):
        self.ensure_one()
        orders = self.env["pos.order"].search([
            ("session_id", "=", session.id),
            ("state", "in", ("paid", "done", "invoiced")),
        ])
        self._collect_totals(orders)
        self._collect_payments(session, orders)
        self._collect_taxes(orders)
        self._collect_categories(orders)
        self._collect_cash(session, orders)

    def _collect_totals(self, orders):
        refunds = orders.filtered(lambda o: o.amount_total < 0)
        sales = orders - refunds
        lines = orders.mapped("lines")

        gross = sum(l.price_unit * l.qty for l in lines)
        net = sum(lines.mapped("price_subtotal"))
        total = sum(orders.mapped("amount_total"))
        self.write({
            "order_count": len(sales),
            "refund_count": len(refunds),
            "item_count": sum(lines.mapped("qty")),
            "gross_sales": gross,
            # Discount is the gap between list price and what was charged,
            # which is the only definition that survives a line discounted
            # twice or priced by a pricelist.
            "discount_total": gross - net,
            "net_sales": net,
            "tax_total": sum(orders.mapped("amount_tax")),
            "total_sales": total,
            "refund_total": sum(refunds.mapped("amount_total")),
            "average_basket": (total / len(sales)) if sales else 0.0,
        })

    def _collect_payments(self, session, orders):
        payments = orders.mapped("payment_ids")
        buckets = {}
        for payment in payments:
            entry = buckets.setdefault(
                payment.payment_method_id, {"amount": 0.0, "count": 0}
            )
            entry["amount"] += payment.amount
            entry["count"] += 1
        # Methods the till offers but nobody used are still listed, at
        # zero: a Z report with a method missing reads as an omission.
        for method in session.payment_method_ids:
            buckets.setdefault(method, {"amount": 0.0, "count": 0})

        values = []
        for method, data in buckets.items():
            values.append({
                "report_id": self.id,
                "kind": PAYMENT,
                "name": method.display_name,
                "amount": data["amount"],
                "count": data["count"],
                "sequence": 10 if method.is_cash_count else 20,
            })
        self.env["mna.pos.zreport.line"].create(values)

    def _collect_taxes(self, orders):
        """Base and tax per rate, computed the way the order itself was."""
        buckets = {}
        untaxed = {"base": 0.0, "tax": 0.0}
        for line in orders.mapped("lines"):
            taxes = line.tax_ids_after_fiscal_position
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            if not taxes:
                untaxed["base"] += line.price_subtotal
                continue
            computed = taxes.compute_all(
                price, line.order_id.currency_id, line.qty,
                product=line.product_id, partner=line.order_id.partner_id,
            )
            for part in computed["taxes"]:
                tax = self.env["account.tax"].browse(part["id"])
                entry = buckets.setdefault(tax, {"base": 0.0, "tax": 0.0})
                entry["base"] += part["base"]
                entry["tax"] += part["amount"]

        values = [
            {
                "report_id": self.id, "kind": TAX, "name": tax.display_name,
                "base": data["base"], "amount": data["tax"], "sequence": 10,
            }
            for tax, data in buckets.items()
        ]
        if untaxed["base"]:
            values.append({
                "report_id": self.id, "kind": TAX, "name": _("No tax"),
                "base": untaxed["base"], "amount": 0.0, "sequence": 90,
            })
        self.env["mna.pos.zreport.line"].create(values)

    def _collect_categories(self, orders):
        buckets = {}
        for line in orders.mapped("lines"):
            category = line.product_id.categ_id
            entry = buckets.setdefault(category, {"amount": 0.0, "qty": 0.0})
            entry["amount"] += line.price_subtotal
            entry["qty"] += line.qty
        self.env["mna.pos.zreport.line"].create([
            {
                "report_id": self.id, "kind": CATEGORY,
                "name": category.display_name or _("Uncategorised"),
                "amount": data["amount"], "quantity": data["qty"],
            }
            for category, data in buckets.items()
        ])

    def _collect_cash(self, session, orders):
        """Cash figures taken from the session's own, not recomputed.

        Odoo captures the manual cash movements into cash_real_transaction
        when the session closes, and afterwards statement_line_ids can
        gain a line for the counting difference itself. Summing the
        statement lines after closing therefore counts money twice. Using
        the session's own expected and difference also means this report
        can never disagree with the session screen an auditor would
        compare it against.
        """
        cash_methods = session.payment_method_ids.filtered("is_cash_count")
        cash_payments = orders.mapped("payment_ids").filtered(
            lambda p: p.payment_method_id in cash_methods
        )
        cash_sales = sum(cash_payments.mapped("amount"))

        # Only the movements a person made while trading. Closing adds two
        # more lines of its own: one carrying the session's cash takings,
        # which is referenced by the session name, and, when the count did
        # not match, one for the difference. Counting either as a cash
        # movement would report the day's takings twice.
        moves = session.sudo().statement_line_ids.filtered(
            lambda m: m.payment_ref != session.name
        )
        closed = session.state == "closed"
        if closed and session.cash_register_difference:
            difference_line = moves.sorted("id")[-1:].filtered(
                lambda m: session.currency_id.is_zero(
                    m.amount - session.cash_register_difference
                )
            )
            moves -= difference_line
        cash_in = sum(m.amount for m in moves if m.amount > 0)
        cash_out = sum(m.amount for m in moves if m.amount < 0)

        self.write({
            "opening_float": session.cash_register_balance_start,
            "cash_sales": cash_sales,
            "cash_in": cash_in,
            "cash_out": cash_out,
            "expected_cash": session.cash_register_balance_end,
            "counted_cash": session.cash_register_balance_end_real if closed else 0.0,
            # An X report is taken mid trade, when nothing has been
            # counted, so reporting a difference there would be noise.
            "cash_difference": session.cash_register_difference if closed else 0.0,
        })

    # ------------------------------------------------------------------
    def write(self, vals):
        protected = set(vals) - {"note"}
        if protected and any(r.report_type == "z" and r.name for r in self):
            # Allowed while the report is still being built, which is the
            # only time its own _collect writes to it.
            if not self.env.context.get("mna_building_report"):
                raise UserError(_(
                    "A Z report is a record of a day that has closed, so its "
                    "figures cannot be edited. You can still add a note."
                ))
        return super().write(vals)

    def unlink(self):
        if any(r.report_type == "z" for r in self):
            raise UserError(_(
                "A Z report cannot be deleted: the sequence it belongs to has "
                "to stay unbroken."
            ))
        return super().unlink()


class MnaPosZReportLine(models.Model):
    _name = "mna.pos.zreport.line"
    _description = "POS X/Z Report Line"
    _order = "kind, sequence, name"

    report_id = fields.Many2one(
        "mna.pos.zreport", required=True, ondelete="cascade", index=True
    )
    currency_id = fields.Many2one(related="report_id.currency_id")
    kind = fields.Selection(
        [(PAYMENT, "Payment Method"), (TAX, "Tax"), (CATEGORY, "Category")],
        required=True,
    )
    sequence = fields.Integer(default=50)
    name = fields.Char(required=True)
    count = fields.Integer(string="Transactions")
    quantity = fields.Float()
    base = fields.Monetary(currency_field="currency_id", string="Base")
    amount = fields.Monetary(currency_field="currency_id")


class PosSession(models.Model):
    _inherit = "pos.session"

    def action_mna_take_report(self):
        """One button on the session, which takes whichever report fits.

        A session that is trading can only give an X; a closed one can
        only give a Z. Asking the user to pick between two buttons that
        are never both valid is a question with one answer.
        """
        self.ensure_one()
        report = self.env["mna.pos.zreport"]
        if self.state == "closed":
            existing = report.search([
                ("session_id", "=", self.id), ("report_type", "=", "z")
            ], limit=1)
            built = existing or report._build(self, "z")
        else:
            built = report._build(self, "x")
        return report._open(built)
