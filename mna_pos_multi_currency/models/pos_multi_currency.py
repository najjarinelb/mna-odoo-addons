from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero, float_round


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    mna_foreign_currency_id = fields.Many2one(
        "res.currency",
        string="Paid in Currency",
        help="Set this to take payment in a currency other than the shop's. "
             "The cashier types the amount the customer hands over in this "
             "currency, and Odoo records the value in the shop's currency.",
    )
    mna_rate_mode = fields.Selection(
        [("live", "Odoo exchange rate"), ("fixed", "Fixed rate")],
        string="Rate",
        default="live",
        required=True,
        help="A fixed rate is what most shops want. A shop posting a rate on "
             "the wall does not want it moving under the cashier halfway "
             "through the day because a feed updated.",
    )
    mna_fixed_rate = fields.Float(
        string="Units per 1",
        digits=(16, 6),
        help="How many units of the payment currency equal one unit of the "
             "shop's currency. If the shop sells in USD and takes LBP at "
             "89,000 to the dollar, this is 89000.",
    )
    # The POS loads a fixed set of models, and res.currency is not among
    # them, so a many2one to it arrives in the browser as null. These two
    # carry the same information as plain values, which survive the trip.
    mna_foreign_code = fields.Char(
        related="mna_foreign_currency_id.name", string="Currency Code", store=True
    )
    mna_foreign_decimals = fields.Integer(
        related="mna_foreign_currency_id.decimal_places", string="Decimals", store=True
    )
    mna_rate_hint = fields.Char(compute="_compute_mna_rate_hint")
    mna_change_in_shop_currency = fields.Boolean(
        string="Give change in shop currency",
        default=True,
        help="Change is normally given in the shop's own currency, because the "
             "till rarely holds small denominations of the other one.",
    )

    @api.depends("mna_foreign_currency_id", "mna_rate_mode", "mna_fixed_rate")
    def _compute_mna_rate_hint(self):
        for method in self:
            if not method.mna_foreign_currency_id:
                method.mna_rate_hint = False
                continue
            rate = method._mna_rate()
            method.mna_rate_hint = _(
                "1 %(shop)s = %(rate)s %(foreign)s",
                shop=method.company_id.currency_id.name,
                rate=("%.6f" % rate).rstrip("0").rstrip("."),
                foreign=method.mna_foreign_currency_id.name,
            )

    @api.constrains("mna_foreign_currency_id", "mna_rate_mode", "mna_fixed_rate")
    def _check_mna_rate(self):
        for method in self:
            if not method.mna_foreign_currency_id:
                continue
            if method.mna_foreign_currency_id == method.company_id.currency_id:
                raise ValidationError(_(
                    "The payment currency is already the shop's currency, so "
                    "there is nothing to convert."
                ))
            if method.mna_rate_mode == "fixed" and method.mna_fixed_rate <= 0:
                raise ValidationError(_(
                    "Set how many %s equal one %s.",
                    method.mna_foreign_currency_id.name,
                    method.company_id.currency_id.name,
                ))

    def _mna_rate(self):
        """Units of the payment currency per one unit of the shop currency."""
        self.ensure_one()
        if not self.mna_foreign_currency_id:
            return 1.0
        if self.mna_rate_mode == "fixed":
            return self.mna_fixed_rate or 1.0
        company = self.company_id or self.env.company
        shop = company.currency_id
        # res.currency.rate is quoted against the company currency already,
        # so the foreign currency's own rate is the figure wanted. Going
        # through _convert would hide that and round on the way.
        rate = self.mna_foreign_currency_id._get_conversion_rate(
            shop, self.mna_foreign_currency_id, company, fields.Date.context_today(self)
        )
        return rate or 1.0

    @api.model
    def _load_pos_data_fields(self, *args, **kwargs):
        # The signature gained and lost arguments between 18 and 19, so take
        # whatever it is given and pass it straight through.
        fields_list = super()._load_pos_data_fields(*args, **kwargs)
        return fields_list + [
            "mna_foreign_code",
            "mna_foreign_decimals",
            "mna_rate_mode",
            "mna_fixed_rate",
            "mna_change_in_shop_currency",
        ]


class PosPayment(models.Model):
    _inherit = "pos.payment"

    mna_amount_foreign = fields.Monetary(
        string="Paid in Other Currency",
        currency_field="mna_foreign_currency_id",
        help="What the customer actually handed over.",
    )
    mna_foreign_currency_id = fields.Many2one(
        "res.currency", string="Payment Currency", readonly=True
    )
    mna_rate_used = fields.Float(
        string="Rate Used",
        digits=(16, 6),
        readonly=True,
        help="The rate at the moment of the sale. Kept on the payment so a "
             "receipt reprinted next year shows the rate that was charged, "
             "not today's.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            method = self.env["pos.payment.method"].browse(vals.get("payment_method_id"))
            if not method or not method.mna_foreign_currency_id:
                continue
            rate = vals.get("mna_rate_used") or method._mna_rate()
            vals["mna_foreign_currency_id"] = method.mna_foreign_currency_id.id
            vals["mna_rate_used"] = rate
            foreign = vals.get("mna_amount_foreign")
            if foreign:
                # The shop currency amount is derived, never trusted from the
                # client: the client could be an old tab with a stale rate.
                shop_currency = method.company_id.currency_id or self.env.company.currency_id
                vals["amount"] = float_round(
                    foreign / rate, precision_rounding=shop_currency.rounding
                )
            elif vals.get("amount"):
                vals["mna_amount_foreign"] = float_round(
                    vals["amount"] * rate,
                    precision_rounding=method.mna_foreign_currency_id.rounding,
                )
        return super().create(vals_list)


class PosSession(models.Model):
    _inherit = "pos.session"

    mna_foreign_line_ids = fields.One2many(
        "mna.pos.session.currency", "session_id", string="Foreign Currency Taken",
        readonly=True,
    )

    def _mna_rebuild_foreign_lines(self):
        """Total what came in per currency, for the cash count at closing."""
        for session in self:
            session.mna_foreign_line_ids.unlink()
            payments = self.env["pos.payment"].search([
                ("session_id", "=", session.id),
                ("mna_foreign_currency_id", "!=", False),
            ])
            buckets = {}
            for payment in payments:
                entry = buckets.setdefault(
                    payment.payment_method_id,
                    {"foreign": 0.0, "shop": 0.0, "count": 0},
                )
                entry["foreign"] += payment.mna_amount_foreign
                entry["shop"] += payment.amount
                entry["count"] += 1
            self.env["mna.pos.session.currency"].create([
                {
                    "session_id": session.id,
                    "payment_method_id": method.id,
                    "currency_id": method.mna_foreign_currency_id.id,
                    "amount_foreign": data["foreign"],
                    "amount_shop": data["shop"],
                    "payment_count": data["count"],
                }
                for method, data in buckets.items()
            ])

    def action_pos_session_closing_control(self, *args, **kwargs):
        result = super().action_pos_session_closing_control(*args, **kwargs)
        self._mna_rebuild_foreign_lines()
        return result


class MnaPosSessionCurrency(models.Model):
    _name = "mna.pos.session.currency"
    _description = "Foreign Currency Taken in a Session"
    _order = "session_id, currency_id"

    session_id = fields.Many2one(
        "pos.session", required=True, ondelete="cascade", index=True
    )
    payment_method_id = fields.Many2one("pos.payment.method", required=True)
    currency_id = fields.Many2one("res.currency", required=True)
    company_currency_id = fields.Many2one(
        related="session_id.company_id.currency_id", string="Shop Currency"
    )
    payment_count = fields.Integer(
        string="Payments", help="How many payments made up this total."
    )
    amount_foreign = fields.Monetary(currency_field="currency_id")
    amount_shop = fields.Monetary(
        currency_field="company_currency_id", string="Value in Shop Currency"
    )
    counted_foreign = fields.Monetary(
        currency_field="currency_id", string="Counted",
        help="What the till actually holds in this currency at close.",
    )
    difference_foreign = fields.Monetary(
        currency_field="currency_id", string="Difference",
        compute="_compute_difference", store=True,
    )

    @api.depends("counted_foreign", "amount_foreign")
    def _compute_difference(self):
        for line in self:
            line.difference_foreign = line.counted_foreign - line.amount_foreign


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _mna_check_change(self):
        """Refuse change larger than the sale in the shop currency.

        Taking a large note in a weak currency and giving change in a
        strong one is how a till is emptied by arithmetic rather than by
        theft, so it is worth stopping rather than reporting later.
        """
        for order in self:
            foreign_payments = order.payment_ids.filtered("mna_foreign_currency_id")
            if not foreign_payments:
                continue
            rounding = order.currency_id.rounding
            # Summed from the payments rather than read from amount_paid,
            # which is a plain field and is not always refreshed by the
            # time this runs.
            paid = sum(order.payment_ids.mapped("amount"))
            change = paid - order.amount_total
            if float_is_zero(change, precision_rounding=rounding) or change < 0:
                continue
            if change > order.amount_total:
                raise UserError(_(
                    "This would give %(change)s change on a sale of %(total)s. "
                    "Check the amount entered: it is usually a rate typed into "
                    "the amount box.",
                    change=order.currency_id.format(change),
                    total=order.currency_id.format(order.amount_total),
                ))
