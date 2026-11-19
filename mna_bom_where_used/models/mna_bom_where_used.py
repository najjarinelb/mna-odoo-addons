# Part of the Najjarine Tech Odoo modules. See LICENSE file for full
# copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class MnaBomWhereUsed(models.TransientModel):
    _name = "mna.bom.where.used"
    _description = "BoM Where Used"

    product_id = fields.Many2one(
        "product.product", string="Component", required=True,
        help="The component to look for. Every bill of materials that "
             "consumes it, at any level, is listed.")
    max_depth = fields.Integer(
        string="Maximum Levels", default=10, required=True,
        help="How far up the structure to climb. Level 1 is the bill of "
             "materials that consumes the component directly.")
    include_inactive = fields.Boolean(
        string="Include Archived BoMs",
        help="Archived bills of materials are skipped unless this is set. "
             "They are worth including when you are checking what an old "
             "revision used to consume.")
    company_id = fields.Many2one(
        "res.company", string="Company",
        default=lambda self: self.env.company,
        help="Leave empty to search bills of materials of every company "
             "you have access to.")
    line_ids = fields.One2many(
        "mna.bom.where.used.line", "wizard_id", string="Results")
    result_count = fields.Integer(
        string="Parents Found", compute="_compute_result_count")
    has_run = fields.Boolean(string="Has Run")
    note = fields.Char(string="Note", readonly=True)

    @api.depends("line_ids")
    def _compute_result_count(self):
        for wizard in self:
            wizard.result_count = len(wizard.line_ids.filtered(
                lambda line: line.kind == "use"))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _bom_domain(self):
        domain = [("bom_line_ids", "!=", False)]
        if self.company_id:
            domain += ["|", ("company_id", "=", self.company_id.id),
                       ("company_id", "=", False)]
        return domain

    @staticmethod
    def _qty_in_product_uom(line):
        """The BoM line quantity expressed in the component's own unit.

        A line entered in grams against a component held in kilograms has
        to be converted before it is multiplied up the path, or the
        roll-up is out by a factor of a thousand.
        """
        if line.product_uom_id and line.product_uom_id != line.product_id.uom_id:
            return line.product_uom_id._compute_quantity(
                line.product_qty, line.product_id.uom_id, round=False)
        return line.product_qty

    @staticmethod
    def _bom_output_qty(bom):
        """The BoM output quantity in the produced product's own unit."""
        product = bom.product_id or bom.product_tmpl_id
        target_uom = product.uom_id
        if bom.product_uom_id and target_uom and bom.product_uom_id != target_uom:
            return bom.product_uom_id._compute_quantity(
                bom.product_qty, target_uom, round=False)
        return bom.product_qty

    def _parent_products(self, bom):
        """The products this BoM produces.

        A BoM set on a template with no variant pinned produces every
        variant of that template, and each of those variants can be a
        component somewhere else.
        """
        if bom.product_id:
            return bom.product_id
        return bom.product_tmpl_id.product_variant_ids

    # ------------------------------------------------------------------
    # the climb
    # ------------------------------------------------------------------
    def action_search(self):
        self.ensure_one()
        if self.max_depth < 1:
            raise UserError(_("The maximum number of levels has to be at "
                              "least 1."))
        self.line_ids.unlink()
        Line = self.env["mna.bom.where.used.line"]
        BomLine = self.env["mrp.bom.line"]

        bom_context = self.with_context(active_test=not self.include_inactive)
        rows = []
        # Each frontier entry is (product, qty of the searched component per
        # one unit of that product, the path of BoM ids walked to get here).
        frontier = [(self.product_id, 1.0, ())]
        depth = 0
        truncated = False

        while frontier:
            depth += 1
            if depth > self.max_depth:
                truncated = True
                break
            next_frontier = []
            products = self.env["product.product"].browse(
                [product.id for product, _qty, _path in frontier])
            parent_lines = BomLine.with_context(
                active_test=not self.include_inactive).search([
                    ("product_id", "in", products.ids),
                ])
            by_product = {}
            for parent_line in parent_lines:
                by_product.setdefault(parent_line.product_id.id,
                                      []).append(parent_line)

            for product, carried_qty, path in frontier:
                for parent_line in by_product.get(product.id, []):
                    bom = parent_line.bom_id
                    if not bom:
                        continue
                    if self.company_id and bom.company_id \
                            and bom.company_id != self.company_id:
                        continue
                    if not self.include_inactive and not bom.active:
                        continue
                    output_qty = self._bom_output_qty(bom)
                    if float_is_zero(output_qty, precision_digits=6):
                        # A BoM that produces nothing cannot be divided
                        # through, and reporting a per-unit figure for it
                        # would be a made up number.
                        rows.append({
                            "kind": "invalid",
                            "level": depth,
                            "bom_id": bom.id,
                            "parent_product_id": (
                                bom.product_id or
                                bom.product_tmpl_id.product_variant_id).id,
                            "component_product_id": product.id,
                            "qty_per_parent": 0.0,
                            "line_qty": parent_line.product_qty,
                            "path": self._format_path(path + (bom.id,)),
                            "message": _("This bill of materials produces a "
                                         "quantity of zero, so a per-unit "
                                         "figure cannot be computed."),
                        })
                        continue
                    line_qty = self._qty_in_product_uom(parent_line)
                    qty_per_parent = carried_qty * line_qty / output_qty
                    new_path = path + (bom.id,)
                    looped = bom.id in path
                    for parent_product in self._parent_products(bom):
                        rows.append({
                            "kind": "loop" if looped else "use",
                            "level": depth,
                            "bom_id": bom.id,
                            "parent_product_id": parent_product.id,
                            "component_product_id": product.id,
                            "qty_per_parent": qty_per_parent,
                            "line_qty": parent_line.product_qty,
                            "path": self._format_path(new_path),
                            "message": _("This bill of materials is already "
                                         "on the path, so the structure "
                                         "loops back on itself. The climb "
                                         "stops here.") if looped else False,
                        })
                        if not looped:
                            next_frontier.append(
                                (parent_product, qty_per_parent, new_path))
            frontier = next_frontier

        if truncated and frontier:
            rows.append({
                "kind": "truncated",
                "level": self.max_depth,
                "qty_per_parent": 0.0,
                "message": _("The depth limit of %s levels was reached "
                             "before the structure ran out. Raise it to see "
                             "the rest.") % self.max_depth,
            })

        for row in rows:
            row["wizard_id"] = self.id
        Line.create(rows)

        uses = len([row for row in rows if row["kind"] == "use"])
        self.has_run = True
        if not uses:
            self.note = _("No bill of materials consumes %s.") \
                % self.product_id.display_name
        else:
            self.note = _("%(count)s parent bills of materials consume "
                          "%(product)s.") % {
                "count": uses, "product": self.product_id.display_name}
        return {
            "type": "ir.actions.act_window",
            # Without a name the dialog falls back to a generic title,
            # which tells the reader nothing about what they are looking
            # at once the wizard has run.
            "name": _("BoM Where Used"),
            "res_model": "mna.bom.where.used",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    def _format_path(self, bom_ids):
        boms = self.env["mrp.bom"].browse(list(bom_ids))
        names = []
        for bom in boms:
            product = bom.product_id or bom.product_tmpl_id
            names.append(product.display_name)
        return " < ".join(names)


class MnaBomWhereUsedLine(models.TransientModel):
    _name = "mna.bom.where.used.line"
    _description = "BoM Where Used Result"
    _order = "level, parent_product_id"

    wizard_id = fields.Many2one(
        "mna.bom.where.used", required=True, ondelete="cascade", index=True)
    kind = fields.Selection([
        ("use", "Used in"),
        ("loop", "Loop detected"),
        ("invalid", "Cannot be computed"),
        ("truncated", "Depth limit reached"),
    ], string="Kind", default="use", required=True)
    level = fields.Integer(
        string="Level",
        help="1 is the bill of materials that consumes the component "
             "directly. 2 is a bill of materials that consumes one of "
             "those, and so on.")
    bom_id = fields.Many2one("mrp.bom", string="Bill of Materials")
    parent_product_id = fields.Many2one("product.product", string="Parent")
    component_product_id = fields.Many2one(
        "product.product", string="Consumed At This Level",
        help="At level 1 this is the component you searched for. Higher up "
             "it is the sub-assembly that carries it.")
    qty_per_parent = fields.Float(
        string="Qty per Parent Unit", digits=(16, 6),
        help="How much of the component you searched for goes into one "
             "unit of this parent, through every level in between.")
    line_qty = fields.Float(
        string="BoM Line Qty", digits=(16, 6),
        help="The quantity as it is written on the bill of materials line, "
             "before it is divided by the batch size.")
    path = fields.Char(string="Path")
    message = fields.Char(string="Message")
    bom_type = fields.Selection(related="bom_id.type", string="BoM Type")

    def action_open_bom(self):
        self.ensure_one()
        if not self.bom_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom",
            "res_id": self.bom_id.id,
            "view_mode": "form",
            "target": "current",
        }
