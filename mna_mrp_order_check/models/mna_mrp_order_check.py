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

# Short labels on purpose, and the same words as the checkboxes that
# switch each rule on. The sentence explaining a finding belongs in the
# message beside it, not in a column heading that then truncates.
CHECKS = [
    ("qty_mismatch", "Quantity Mismatch"),
    ("not_consumed", "Never Consumed"),
    ("over_consumed", "Over Consumed"),
    ("zero_cost", "No Cost Recorded"),
    ("no_duration", "No Time Logged"),
    ("no_output", "No Output Movement"),
]


class MnaMrpOrderCheck(models.TransientModel):
    _name = "mna.mrp.order.check"
    _description = "Manufacturing Order Check"

    date_from = fields.Date(
        string="From", required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(
        string="To", required=True,
        default=lambda self: fields.Date.context_today(self))
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company)
    over_consumption_tolerance = fields.Float(
        string="Over-consumption Tolerance (%)", default=10.0,
        help="A component consumed over plan by less than this is not "
             "reported. Some scrap is normal, and a report that calls "
             "every gram of it a problem gets switched off.")
    check_qty_mismatch = fields.Boolean(string="Quantity Mismatch",
                                        default=True)
    check_not_consumed = fields.Boolean(string="Never Consumed", default=True)
    check_over_consumed = fields.Boolean(string="Over Consumed", default=True)
    check_zero_cost = fields.Boolean(string="No Cost Recorded", default=True)
    check_no_duration = fields.Boolean(string="No Time Logged", default=True)
    check_no_output = fields.Boolean(string="No Output Movement", default=True)

    line_ids = fields.One2many(
        "mna.mrp.order.check.line", "wizard_id", string="Findings")
    has_run = fields.Boolean()
    note = fields.Char(readonly=True)
    order_count = fields.Integer(string="Orders Scanned", readonly=True)

    # ------------------------------------------------------------------
    # version bridges, so one source serves 18 and 19
    # ------------------------------------------------------------------
    @api.model
    def _is_storable(self, product):
        """Odoo 18 introduced is_storable; before that it was type."""
        if "is_storable" in product._fields:
            return bool(product.is_storable)
        return product.type == "product"

    @api.model
    def _rounding(self, product):
        uom = product.uom_id
        return uom.rounding if uom and uom.rounding else 0.01

    # ------------------------------------------------------------------
    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("The start date is after the end date."))
        self.line_ids.unlink()

        productions = self.env["mrp.production"].search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "done"),
            ("date_finished", ">=", fields.Datetime.to_datetime(
                self.date_from)),
            ("date_finished", "<=", fields.Datetime.to_datetime(
                self.date_to).replace(hour=23, minute=59, second=59)),
        ], order="date_finished desc")

        rows = []
        for production in productions:
            rows += self._check_production(production)
        for row in rows:
            row["wizard_id"] = self.id
        self.env["mna.mrp.order.check.line"].create(rows)

        self.has_run = True
        self.order_count = len(productions)
        if not rows:
            self.note = _("%s finished manufacturing orders checked. "
                          "Nothing to report.") % len(productions)
        else:
            self.note = _("%(findings)s findings across %(orders)s finished "
                          "manufacturing orders.") % {
                "findings": len(rows), "orders": len(productions)}
        return {
            "type": "ir.actions.act_window",
            # Without a name the dialog falls back to a generic title,
            # which tells the reader nothing about what they are looking
            # at once the wizard has run.
            "name": _("Manufacturing Order Check"),
            "res_model": "mna.mrp.order.check",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    def _check_production(self, production):
        rows = []
        base = {"production_id": production.id}

        if self.check_qty_mismatch:
            rows += self._check_qty_mismatch(production, base)
        if self.check_no_output:
            rows += self._check_no_output(production, base)
        if self.check_no_duration:
            rows += self._check_no_duration(production, base)

        for move in production.move_raw_ids:
            if not move.product_id:
                continue
            component_base = dict(base, product_id=move.product_id.id)
            # A component that was never consumed does not survive as a
            # done move: Odoo cancels it when the order closes and clears
            # the picked flag, while leaving the planned quantity on the
            # record. That cancelled move is the only trace left, so it
            # has to be read rather than skipped.
            if self.check_not_consumed:
                rows += self._check_not_consumed(move, component_base)
            if move.state == "cancel":
                # Nothing was consumed, so there is no quantity to call
                # excessive and no cost to call missing.
                continue
            if self.check_over_consumed:
                rows += self._check_over_consumed(move, component_base)
            if self.check_zero_cost:
                rows += self._check_zero_cost(move, component_base)
        return rows

    # -- individual rules ----------------------------------------------
    def _check_qty_mismatch(self, production, base):
        rounding = self._rounding(production.product_id)
        ordered = production.product_qty
        produced = production.qty_produced
        if float_compare(produced, ordered,
                         precision_rounding=rounding) == 0:
            return []
        short = ordered - produced
        return [dict(base,
                     check="qty_mismatch",
                     severity="high" if short > 0 else "medium",
                     planned_qty=ordered,
                     actual_qty=produced,
                     difference=produced - ordered,
                     message=_("Ordered %(ordered)s, produced "
                               "%(produced)s.") % {
                         "ordered": ordered, "produced": produced})]

    def _check_no_output(self, production, base):
        done_output = production.move_finished_ids.filtered(
            lambda move: move.state == "done"
            and move.product_id == production.product_id)
        total = sum(done_output.mapped("quantity"))
        rounding = self._rounding(production.product_id)
        if not float_is_zero(total, precision_rounding=rounding):
            return []
        return [dict(base,
                     check="no_output",
                     severity="high",
                     planned_qty=production.product_qty,
                     actual_qty=0.0,
                     difference=-production.product_qty,
                     message=_("The order is finished but no finished-goods "
                               "movement carries any quantity, so nothing "
                               "reached stock."))]

    def _check_no_duration(self, production, base):
        workorders = production.workorder_ids.filtered(
            lambda wo: wo.state != "cancel")
        if not workorders:
            return []
        expected = sum(workorders.mapped("duration_expected"))
        actual = sum(workorders.mapped("duration"))
        if not float_is_zero(actual, precision_digits=2):
            return []
        if float_is_zero(expected, precision_digits=2):
            # Nothing was planned either, so there is no labour cost to
            # lose and nothing to complain about.
            return []
        return [dict(base,
                     check="no_duration",
                     severity="medium",
                     planned_qty=expected,
                     actual_qty=0.0,
                     difference=-expected,
                     message=_("%(count)s work orders planned %(expected)s "
                               "minutes and logged none, so the labour cost "
                               "of this order is zero.") % {
                         "count": len(workorders), "expected": expected})]

    def _check_not_consumed(self, move, base):
        rounding = self._rounding(move.product_id)
        planned = move.product_uom_qty
        actual = move.quantity if move.picked else 0.0
        if float_is_zero(planned, precision_rounding=rounding):
            return []
        if not float_is_zero(actual, precision_rounding=rounding):
            return []
        return [dict(base,
                     check="not_consumed",
                     severity="high",
                     planned_qty=planned,
                     actual_qty=0.0,
                     difference=-planned,
                     message=_("%(qty)s %(uom)s was planned and none "
                               "was consumed%(cancelled)s, so stock is "
                               "overstated and the cost of what you made "
                               "is understated.") % {
                         "qty": planned,
                         "uom": move.product_uom.name or "",
                         "cancelled": _(" (the component movement was "
                                        "cancelled when the order closed)")
                         if move.state == "cancel" else ""})]

    def _check_over_consumed(self, move, base):
        rounding = self._rounding(move.product_id)
        planned = move.product_uom_qty
        actual = move.quantity if move.picked else 0.0
        if float_is_zero(planned, precision_rounding=rounding):
            return []
        if float_is_zero(actual, precision_rounding=rounding):
            # Already covered, and reporting it twice is noise.
            return []
        if self._flexible_consumption(move):
            return []
        limit = planned * (1.0 + (self.over_consumption_tolerance / 100.0))
        if float_compare(actual, limit, precision_rounding=rounding) <= 0:
            return []
        over_pct = (actual - planned) / planned * 100.0
        return [dict(base,
                     check="over_consumed",
                     severity="medium",
                     planned_qty=planned,
                     actual_qty=actual,
                     difference=actual - planned,
                     message=_("Consumed %(actual)s against a plan of "
                               "%(planned)s, which is %(pct).1f%% over.") % {
                         "actual": actual, "planned": planned,
                         "pct": over_pct})]

    def _flexible_consumption(self, move):
        """A BoM set to flexible consumption is meant to vary.

        Reporting those orders for consuming a different quantity is
        arguing with a setting somebody chose on purpose.
        """
        bom = move.raw_material_production_id.bom_id
        return bool(bom) and bom.consumption == "flexible"

    def _check_zero_cost(self, move, base):
        product = move.product_id
        if not self._is_storable(product):
            # A service or a non-stocked consumable with no cost is
            # ordinary and not worth a line.
            return []
        if not float_is_zero(product.standard_price, precision_digits=4):
            return []
        consumed = move.quantity if move.picked else 0.0
        rounding = self._rounding(product)
        if float_is_zero(consumed, precision_rounding=rounding):
            return []
        return [dict(base,
                     check="zero_cost",
                     severity="low",
                     planned_qty=move.product_uom_qty,
                     actual_qty=consumed,
                     difference=0.0,
                     message=_("%(qty)s was consumed at a recorded cost of "
                               "zero, so this order looks cheaper than it "
                               "was.") % {"qty": consumed})]


class MnaMrpOrderCheckLine(models.TransientModel):
    _name = "mna.mrp.order.check.line"
    _description = "Manufacturing Order Check Finding"
    _order = "severity, production_id, check"

    wizard_id = fields.Many2one(
        "mna.mrp.order.check", required=True, ondelete="cascade", index=True)
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", required=True)
    product_id = fields.Many2one("product.product", string="Component")
    check = fields.Selection(CHECKS, string="Finding", required=True)
    severity = fields.Selection(SEVERITIES, string="Severity", required=True)
    planned_qty = fields.Float(string="Planned", digits=(16, 4))
    actual_qty = fields.Float(string="Actual", digits=(16, 4))
    difference = fields.Float(string="Difference", digits=(16, 4))
    message = fields.Char(string="What it means")
    production_state = fields.Selection(
        related="production_id.state", string="Status")
    date_finished = fields.Datetime(
        related="production_id.date_finished", string="Finished")

    def action_open_production(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.production",
            "res_id": self.production_id.id,
            "view_mode": "form",
            "target": "current",
        }
