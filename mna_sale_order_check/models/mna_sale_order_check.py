# Part of the Najjarine Tech Odoo modules. See LICENSE file for full
# copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

SEVERITIES = [
    ("high", "High"),
    ("medium", "Medium"),
    ("low", "Low"),
]

# The same words as the checkboxes that switch each rule on. A finding
# needs a short label here and its sentence in the message column, not a
# heading long enough to truncate.
CHECKS = [
    ("below_cost", "Sold Below Cost"),
    ("discount_high", "Discount Over Limit"),
    ("zero_price", "Priced At Zero"),
    ("delivered_not_invoiced", "Delivered Not Invoiced"),
    ("over_invoiced", "Invoiced Over Delivered"),
    ("expired_open", "Expired Still Open"),
    ("no_salesperson", "No Salesperson"),
]


class MnaSaleOrderCheck(models.TransientModel):
    _name = "mna.sale.order.check"
    _description = "Sales Order Check"

    date_from = fields.Date(
        string="From", required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(
        string="To", required=True,
        default=lambda self: fields.Date.context_today(self))
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company)
    discount_limit = fields.Float(
        string="Discount Limit (%)", default=20.0,
        help="A line discounted by more than this is reported. Set it to "
             "the highest discount a salesperson may give without asking, "
             "so the report shows only the ones that went past it.")
    invoice_grace_days = fields.Integer(
        string="Invoicing Grace (days)", default=7,
        help="A delivery invoiced within this many days is not reported. "
             "Invoicing runs on a cycle in most companies, and a report "
             "that flags yesterday's delivery is noise.")

    check_below_cost = fields.Boolean(string="Sold Below Cost", default=True)
    check_discount_high = fields.Boolean(
        string="Discount Over Limit", default=True)
    check_zero_price = fields.Boolean(string="Priced At Zero", default=True)
    check_delivered_not_invoiced = fields.Boolean(
        string="Delivered Not Invoiced", default=True)
    check_over_invoiced = fields.Boolean(
        string="Invoiced Over Delivered", default=True)
    check_expired_open = fields.Boolean(
        string="Expired Still Open", default=True)
    check_no_salesperson = fields.Boolean(
        string="No Salesperson", default=True)

    line_ids = fields.One2many(
        "mna.sale.order.check.line", "wizard_id", string="Findings")
    has_run = fields.Boolean()
    note = fields.Char(readonly=True)
    order_count = fields.Integer(string="Orders Scanned", readonly=True)

    # ------------------------------------------------------------------
    # version bridges, so one source serves 18 and 19
    # ------------------------------------------------------------------
    @api.model
    def _line_uom(self, line):
        """sale.order.line.product_uom became product_uom_id in 19."""
        if "product_uom_id" in line._fields:
            return line.product_uom_id
        return line.product_uom

    @api.model
    def _rounding(self, product):
        uom = product.uom_id
        return uom.rounding if uom and uom.rounding else 0.01

    @api.model
    def _line_cost(self, line):
        """Unit cost in the line's own unit of measure.

        sale_margin stores a per-line purchase price, which is the right
        figure when it is there because it is the cost as at the order.
        Without that module the product's current cost is the only thing
        available, and it is held in the product's own unit of measure,
        so a line sold in a different unit has to be converted or the
        comparison is out by the conversion factor.
        """
        if "purchase_price" in line._fields and not float_is_zero(
                line.purchase_price, precision_digits=4):
            return line.purchase_price
        product = line.product_id
        cost = product.standard_price
        if float_is_zero(cost, precision_digits=4):
            return 0.0
        line_uom = self._line_uom(line)
        if line_uom and product.uom_id and line_uom != product.uom_id:
            # One unit of the line's UoM, expressed in the product's UoM,
            # is what one unit of the line actually costs.
            cost = line_uom._compute_quantity(
                1.0, product.uom_id, round=False) * cost
        return cost

    # ------------------------------------------------------------------
    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("The start date is after the end date."))
        if self.discount_limit < 0.0 or self.discount_limit > 100.0:
            raise UserError(_("The discount limit has to be between 0 and "
                              "100 percent."))
        self.line_ids.unlink()

        orders = self.env["sale.order"].search([
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("draft", "sent", "sale")),
            ("date_order", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("date_order", "<=", fields.Datetime.to_datetime(
                self.date_to).replace(hour=23, minute=59, second=59)),
        ], order="date_order desc")

        rows = []
        for order in orders:
            rows += self._check_order(order)
        for row in rows:
            row["wizard_id"] = self.id
        self.env["mna.sale.order.check.line"].create(rows)

        self.has_run = True
        self.order_count = len(orders)
        if not rows:
            self.note = _("%s sales orders checked. Nothing to report.") % (
                len(orders),)
        else:
            self.note = _("%(findings)s findings across %(orders)s sales "
                          "orders.") % {"findings": len(rows),
                                        "orders": len(orders)}
        return {
            "type": "ir.actions.act_window",
            # Without a name the dialog falls back to a generic title,
            # which tells the reader nothing once the wizard has run.
            "name": _("Sales Order Check"),
            "res_model": "mna.sale.order.check",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    def _check_order(self, order):
        rows = []
        base = {"order_id": order.id}
        confirmed = order.state == "sale"

        if self.check_expired_open and not confirmed:
            rows += self._check_expired_open(order, base)
        if self.check_no_salesperson and confirmed:
            rows += self._check_no_salesperson(order, base)
        if confirmed:
            rows += self._check_order_invoicing(order, base)

        for line in order.order_line:
            if line.display_type:
                # A section or a note carries no product and no price.
                continue
            line_base = dict(base, line_id=line.id,
                             product_id=line.product_id.id or False)
            if self.check_below_cost and confirmed:
                rows += self._check_below_cost(line, line_base)
            if self.check_discount_high:
                rows += self._check_discount_high(line, line_base)
            if self.check_zero_price and confirmed:
                rows += self._check_zero_price(line, line_base)
            if self.check_over_invoiced and confirmed:
                rows += self._check_over_invoiced(line, line_base)
        return rows

    # ------------------------------------------------------------------
    def _check_expired_open(self, order, base):
        """A quotation past its own validity date, still sitting open.

        Only reported when the order carries a validity date, because a
        quotation without one was never given an expiry to miss.
        """
        today = fields.Date.context_today(self)
        if not order.validity_date or order.validity_date >= today:
            return []
        days = (today - order.validity_date).days
        return [dict(base,
                     check="expired_open",
                     severity="low",
                     message=_("Expired %(days)s days ago, on %(date)s, and "
                               "is still open.") % {
                         "days": days, "date": order.validity_date})]

    def _check_no_salesperson(self, order, base):
        if order.user_id:
            return []
        return [dict(base,
                     check="no_salesperson",
                     severity="low",
                     message=_("Confirmed with no salesperson set, so it "
                               "lands in nobody's figures."))]

    def _check_below_cost(self, line, base):
        """A line whose unit price is under what the goods cost.

        Compared on the unit price after discount, because that is what
        the customer pays. A line at zero cost is not reported: there is
        nothing to compare against, and saying every such line loses
        money would be a lie.
        """
        cost = self._line_cost(line)
        if float_is_zero(cost, precision_digits=4):
            return []
        if float_is_zero(line.product_uom_qty,
                         precision_rounding=self._rounding(line.product_id)):
            return []
        net_unit = line.price_unit * (1.0 - (line.discount or 0.0) / 100.0)
        if float_compare(net_unit, cost, precision_digits=4) >= 0:
            return []
        loss = (cost - net_unit) * line.product_uom_qty
        return [dict(base,
                     check="below_cost",
                     severity="high",
                     expected=cost,
                     actual=net_unit,
                     difference=-loss,
                     message=_("Sold at %(price).2f against a cost of "
                               "%(cost).2f, so the line loses %(loss).2f "
                               "over %(qty)s.") % {
                         "price": net_unit, "cost": cost, "loss": loss,
                         "qty": line.product_uom_qty})]

    def _check_discount_high(self, line, base):
        discount = line.discount or 0.0
        if float_compare(discount, self.discount_limit,
                         precision_digits=2) <= 0:
            return []
        given_up = line.price_unit * line.product_uom_qty * discount / 100.0
        return [dict(base,
                     check="discount_high",
                     severity="medium",
                     expected=self.discount_limit,
                     actual=discount,
                     difference=discount - self.discount_limit,
                     message=_("Discounted %(discount).2f%% against a limit "
                               "of %(limit).2f%%, which gives up "
                               "%(amount).2f.") % {
                         "discount": discount, "limit": self.discount_limit,
                         "amount": given_up})]

    def _check_zero_price(self, line, base):
        """A line at zero price that nobody meant to give away.

        A deliberate freebie is entered as a full discount, so a line at
        zero with a discount on it is left alone. A line at zero with no
        discount is a price that was never filled in.
        """
        rounding = self._rounding(line.product_id)
        if float_is_zero(line.product_uom_qty, precision_rounding=rounding):
            return []
        if not float_is_zero(line.price_unit, precision_digits=4):
            return []
        if not float_is_zero(line.discount or 0.0, precision_digits=2):
            return []
        return [dict(base,
                     check="zero_price",
                     severity="medium",
                     expected=0.0,
                     actual=0.0,
                     message=_("%(qty)s at a price of zero with no discount "
                               "recorded, so the price was never "
                               "set.") % {"qty": line.product_uom_qty})]

    def _check_over_invoiced(self, line, base):
        """More invoiced than ever went out of the door.

        Services and anything invoiced on the ordered quantity are left
        alone, because for those the delivered quantity is not what
        invoicing is measured against.
        """
        if line.product_id and line.product_id.invoice_policy == "order":
            return []
        if line.product_id and line.product_id.type == "service":
            return []
        rounding = self._rounding(line.product_id)
        if float_compare(line.qty_invoiced, line.qty_delivered,
                         precision_rounding=rounding) <= 0:
            return []
        return [dict(base,
                     check="over_invoiced",
                     severity="high",
                     expected=line.qty_delivered,
                     actual=line.qty_invoiced,
                     difference=line.qty_invoiced - line.qty_delivered,
                     message=_("Invoiced %(invoiced)s against %(delivered)s "
                               "delivered, so %(diff)s was billed and never "
                               "shipped.") % {
                         "invoiced": line.qty_invoiced,
                         "delivered": line.qty_delivered,
                         "diff": line.qty_invoiced - line.qty_delivered})]

    def _check_order_invoicing(self, order, base):
        """Goods gone, invoice never raised.

        Measured at order level because that is where invoicing is
        decided, and only once the grace period has run out. An order
        with nothing delivered yet has nothing to invoice and is not
        reported.
        """
        if order.invoice_status in ("invoiced", "no"):
            return []
        delivered_any = False
        for line in order.order_line:
            if line.display_type:
                continue
            rounding = self._rounding(line.product_id)
            if not float_is_zero(line.qty_delivered,
                                 precision_rounding=rounding):
                delivered_any = True
                break
        if not delivered_any:
            return []
        today = fields.Date.context_today(self)
        order_date = fields.Datetime.context_timestamp(
            self, order.date_order).date() if order.date_order else today
        age = (today - order_date).days
        if age < self.invoice_grace_days:
            return []
        return [dict(base,
                     check="delivered_not_invoiced",
                     severity="high",
                     expected=float(self.invoice_grace_days),
                     actual=float(age),
                     difference=float(age - self.invoice_grace_days),
                     message=_("Delivered and still not invoiced "
                               "%(age)s days after the order, past a grace "
                               "of %(grace)s.") % {
                         "age": age, "grace": self.invoice_grace_days})]


class MnaSaleOrderCheckLine(models.TransientModel):
    _name = "mna.sale.order.check.line"
    _description = "Sales Order Check Finding"
    _order = "severity, order_id, check"

    wizard_id = fields.Many2one(
        "mna.sale.order.check", required=True, ondelete="cascade", index=True)
    order_id = fields.Many2one(
        "sale.order", string="Sales Order", required=True)
    line_id = fields.Many2one("sale.order.line", string="Order Line")
    product_id = fields.Many2one("product.product", string="Product")
    check = fields.Selection(CHECKS, string="Finding", required=True)
    severity = fields.Selection(SEVERITIES, string="Severity", required=True)
    expected = fields.Float(string="Expected", digits=(16, 4))
    actual = fields.Float(string="Actual", digits=(16, 4))
    difference = fields.Float(string="Difference", digits=(16, 4))
    message = fields.Char(string="What it means")
    partner_id = fields.Many2one(
        related="order_id.partner_id", string="Customer")
    order_state = fields.Selection(related="order_id.state", string="Status")
    date_order = fields.Datetime(related="order_id.date_order", string="Date")
    salesperson_id = fields.Many2one(
        related="order_id.user_id", string="Salesperson")

    def action_open_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": self.order_id.id,
            "view_mode": "form",
            "target": "current",
        }
