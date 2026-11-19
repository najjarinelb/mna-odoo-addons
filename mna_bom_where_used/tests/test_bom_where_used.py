# Part of the Najjarine Tech Odoo modules.
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBomWhereUsed(TransactionCase):
    """The arithmetic in these tests is written out by hand in the
    comments so a reader can check it without running anything.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env.ref("uom.product_uom_unit")
        Product = cls.env["product.product"]
        cls.screw = Product.create({
            "name": "MNA Screw M4", "standard_price": 0.5,
            "uom_id": cls.unit.id})
        cls.subassy = Product.create({
            "name": "MNA Sub-assembly", "uom_id": cls.unit.id})
        cls.widget = Product.create({
            "name": "MNA Widget", "uom_id": cls.unit.id})
        cls.finished = Product.create({
            "name": "MNA Finished Machine", "uom_id": cls.unit.id})
        cls.orphan = Product.create({
            "name": "MNA Orphan Part", "uom_id": cls.unit.id})

        Bom = cls.env["mrp.bom"]
        # Sub-assembly: a batch of 1 consumes 4 screws, so 4 per unit.
        cls.bom_subassy = Bom.create({
            "product_tmpl_id": cls.subassy.product_tmpl_id.id,
            "product_id": cls.subassy.id,
            "product_qty": 1.0,
            "product_uom_id": cls.unit.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": cls.screw.id, "product_qty": 4.0,
                "product_uom_id": cls.unit.id})],
        })
        # Widget: a batch of 1 consumes 5 screws, so 5 per unit.
        cls.bom_widget = Bom.create({
            "product_tmpl_id": cls.widget.product_tmpl_id.id,
            "product_id": cls.widget.id,
            "product_qty": 1.0,
            "product_uom_id": cls.unit.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": cls.screw.id, "product_qty": 5.0,
                "product_uom_id": cls.unit.id})],
        })
        # Finished machine: a batch of 2 consumes 3 sub-assemblies, so
        # 3 / 2 = 1.5 sub-assemblies per unit.
        cls.bom_finished = Bom.create({
            "product_tmpl_id": cls.finished.product_tmpl_id.id,
            "product_id": cls.finished.id,
            "product_qty": 2.0,
            "product_uom_id": cls.unit.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": cls.subassy.id, "product_qty": 3.0,
                "product_uom_id": cls.unit.id})],
        })

    def _run(self, product, **kwargs):
        values = {"product_id": product.id}
        values.update(kwargs)
        wizard = self.env["mna.bom.where.used"].create(values)
        wizard.action_search()
        return wizard

    def _uses(self, wizard):
        """Results keyed by parent product, use lines only."""
        return {
            line.parent_product_id: line
            for line in wizard.line_ids.filtered(lambda l: l.kind == "use")
        }

    # ------------------------------------------------------------------
    # the clean case
    # ------------------------------------------------------------------
    def test_direct_use_quantity(self):
        """A batch of 1 consuming 4 gives 4 per unit, not something else."""
        wizard = self._run(self.screw, max_depth=1)
        uses = self._uses(wizard)
        self.assertIn(self.subassy, uses)
        self.assertIn(self.widget, uses)
        # 4 screws / batch of 1 = 4.0
        self.assertAlmostEqual(uses[self.subassy].qty_per_parent, 4.0, 6)
        # 5 screws / batch of 1 = 5.0
        self.assertAlmostEqual(uses[self.widget].qty_per_parent, 5.0, 6)
        self.assertEqual(uses[self.subassy].level, 1)

    def test_multi_level_rolls_through_batch_size(self):
        """The screw count inside the finished machine is 6, not 12.

        sub-assemblies per machine = 3 / 2 = 1.5
        screws per sub-assembly    = 4 / 1 = 4.0
        screws per machine         = 1.5 * 4.0 = 6.0

        Reporting the raw BoM line quantities instead would give
        3 * 4 = 12, which is the mistake this module exists to avoid.
        """
        wizard = self._run(self.screw, max_depth=5)
        uses = self._uses(wizard)
        self.assertIn(self.finished, uses)
        self.assertAlmostEqual(uses[self.finished].qty_per_parent, 6.0, 6)
        self.assertEqual(uses[self.finished].level, 2)
        self.assertEqual(wizard.result_count, 3)

    def test_path_is_reported(self):
        wizard = self._run(self.screw, max_depth=5)
        line = self._uses(wizard)[self.finished]
        self.assertIn("Sub-assembly", line.path)
        self.assertIn("Finished Machine", line.path)

    def test_uom_conversion(self):
        """Grams on the line against a component held in kilograms.

        A BoM line of 2500 g against a component whose own unit is kg has
        to roll up as 2.5 kg per unit. Multiplying 2500 would be out by a
        factor of a thousand.
        """
        kgm = self.env.ref("uom.product_uom_kgm")
        gram = self.env.ref("uom.product_uom_gram")
        powder = self.env["product.product"].create({
            "name": "MNA Powder", "uom_id": kgm.id})
        mix = self.env["product.product"].create({
            "name": "MNA Mix", "uom_id": self.unit.id})
        self.env["mrp.bom"].create({
            "product_tmpl_id": mix.product_tmpl_id.id,
            "product_id": mix.id,
            "product_qty": 1.0,
            "product_uom_id": self.unit.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": powder.id, "product_qty": 2500.0,
                "product_uom_id": gram.id})],
        })
        wizard = self._run(powder, max_depth=2)
        line = self._uses(wizard)[mix]
        self.assertAlmostEqual(line.qty_per_parent, 2.5, 6)
        # The raw line quantity is still reported untouched, so the
        # reader can see where the converted figure came from.
        self.assertAlmostEqual(line.line_qty, 2500.0, 6)

    # ------------------------------------------------------------------
    # the failure cases, which is where a report like this earns trust
    # ------------------------------------------------------------------
    def test_unused_component_is_silent(self):
        """A component in no BoM gives no rows and no false positives."""
        wizard = self._run(self.orphan, max_depth=10)
        self.assertEqual(wizard.line_ids, self.env["mna.bom.where.used.line"])
        self.assertEqual(wizard.result_count, 0)
        self.assertIn("No bill of materials", wizard.note)

    def test_depth_limit_stops_and_says_so(self):
        """Stopping at the limit is reported, not passed off as the end."""
        wizard = self._run(self.screw, max_depth=1)
        truncated = wizard.line_ids.filtered(lambda l: l.kind == "truncated")
        self.assertTrue(truncated,
                        "A depth limit that cut the climb short has to be "
                        "reported, or the reader thinks they saw it all.")
        self.assertNotIn(self.finished, self._uses(wizard))
        # And with room to run, there is nothing to report.
        full = self._run(self.screw, max_depth=5)
        self.assertFalse(full.line_ids.filtered(
            lambda l: l.kind == "truncated"))

    def test_loop_does_not_hang(self):
        """A BoM structure that reaches itself is flagged, not followed.

        Odoo's own constraint refuses to create a cycle through the ORM,
        so the line is inserted straight into the table. That is not an
        artificial case: cycles reach live databases through data imports
        and through module updates that write BoM lines directly, and the
        report still has to come back rather than fill memory.
        """
        screw_bom = self.env["mrp.bom"].create({
            "product_tmpl_id": self.screw.product_tmpl_id.id,
            "product_id": self.screw.id,
            "product_qty": 1.0,
            "product_uom_id": self.unit.id,
            "type": "normal",
        })
        self.env.cr.execute(
            """
            INSERT INTO mrp_bom_line
                (bom_id, product_id, product_tmpl_id, product_qty,
                 product_uom_id, sequence, company_id,
                 create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, 1.0, %s, 1, %s, 1, 1, now(), now())
            """,
            (screw_bom.id, self.subassy.id,
             self.subassy.product_tmpl_id.id, self.unit.id,
             self.env.company.id),
        )
        self.env.invalidate_all()
        wizard = self._run(self.screw, max_depth=20)
        loops = wizard.line_ids.filtered(lambda l: l.kind == "loop")
        self.assertTrue(loops, "The loop has to be reported explicitly.")
        # And the clean structures around it are still reported.
        self.assertIn(self.widget, self._uses(wizard))

    def test_zero_output_bom_is_flagged_not_divided(self):
        """A BoM producing zero cannot be divided through, so say so."""
        ghost = self.env["product.product"].create({
            "name": "MNA Ghost", "uom_id": self.unit.id})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": ghost.product_tmpl_id.id,
            "product_id": ghost.id,
            "product_qty": 1.0,
            "product_uom_id": self.unit.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": self.orphan.id, "product_qty": 2.0,
                "product_uom_id": self.unit.id})],
        })
        # A zero output quantity cannot be created through the ORM or
        # even stored while the table constraint is in place, so the
        # constraint is dropped for the length of this transaction. This
        # is the shape corrupt data arrives in after a bad import or a
        # hand written UPDATE, and the report must not divide by it.
        self.env.cr.execute(
            "ALTER TABLE mrp_bom DROP CONSTRAINT mrp_bom_qty_positive")
        self.env.cr.execute(
            "UPDATE mrp_bom SET product_qty = 0 WHERE id = %s", (bom.id,))
        bom.invalidate_recordset(["product_qty"])
        wizard = self._run(self.orphan, max_depth=3)
        invalid = wizard.line_ids.filtered(lambda l: l.kind == "invalid")
        self.assertTrue(invalid,
                        "A zero output BoM has to be reported rather than "
                        "silently producing a division by zero or a made "
                        "up per-unit figure.")
        self.assertEqual(wizard.result_count, 0)

    def test_bad_depth_is_rejected(self):
        wizard = self.env["mna.bom.where.used"].create({
            "product_id": self.screw.id, "max_depth": 0})
        with self.assertRaises(UserError):
            wizard.action_search()

    def test_archived_bom_excluded_by_default(self):
        self.bom_widget.active = False
        wizard = self._run(self.screw, max_depth=3)
        self.assertNotIn(self.widget, self._uses(wizard),
                         "An archived BoM should not appear unless asked "
                         "for.")
        with_archived = self._run(self.screw, max_depth=3,
                                  include_inactive=True)
        self.assertIn(self.widget, self._uses(with_archived))
