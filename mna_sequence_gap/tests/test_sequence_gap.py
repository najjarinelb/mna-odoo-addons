from datetime import timedelta

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.mna_sequence_gap.models.mna_sequence_gap import split_name


@tagged("post_install", "-at_install")
class TestSequenceGap(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.journal = cls.company_data["default_journal_sale"]

    def _invoice(self, name=None, date=None, post=True):
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner_a.id,
            "journal_id": self.journal.id,
            "invoice_date": date or self.today,
            "date": date or self.today,
            "invoice_line_ids": [Command.create({
                "product_id": self.product_a.id, "quantity": 1,
                "price_unit": 100, "tax_ids": False})],
        })
        if post:
            move.action_post()
        if name:
            move.name = name
        return move

    def _wizard(self, **vals):
        base = {
            "date_from": self.today - timedelta(days=365),
            "date_to": self.today + timedelta(days=400),
            "journal_ids": [Command.set(self.journal.ids)],
        }
        base.update(vals)
        return self.env["mna.sequence.gap.wizard"].create(base)

    def test_split_name(self):
        self.assertEqual(split_name("INV/2026/00123"), ("INV/2026/", 123, 5))
        self.assertEqual(split_name("BILL-7"), ("BILL-", 7, 1))
        self.assertIsNone(split_name("MANUAL REF"))
        self.assertIsNone(split_name(False))

    def test_clean_sequence_reports_nothing(self):
        for i in range(1, 4):
            self._invoice(name="SEQ/2026/%05d" % i)
        wizard = self._wizard()
        wizard.action_check()
        self.assertEqual(wizard.gap_count, 0)
        self.assertEqual(wizard.duplicate_count, 0)
        self.assertGreaterEqual(wizard.checked_count, 3)

    def test_gap_is_found(self):
        self._invoice(name="GAP/2026/00001")
        self._invoice(name="GAP/2026/00002")
        self._invoice(name="GAP/2026/00005")
        wizard = self._wizard()
        wizard.action_check()
        gaps = wizard.line_ids.filtered(lambda l: l.kind == "gap" and l.prefix == "GAP/2026/")
        self.assertEqual(sorted(gaps.mapped("number")), [3, 4])
        self.assertEqual(sorted(gaps.mapped("expected_name")),
                         ["GAP/2026/00003", "GAP/2026/00004"])

    def test_duplicate_is_found(self):
        # Odoo's unique index covers posted moves only, so the realistic
        # duplicate is a draft that reuses a number already posted.
        a = self._invoice(name="DUP/2026/00007")
        b = self._invoice(post=False)
        b.name = "DUP/2026/00007"
        wizard = self._wizard(include_draft=True)
        wizard.action_check()
        dup = wizard.line_ids.filtered(
            lambda l: l.kind == "duplicate" and l.prefix == "DUP/2026/")
        self.assertEqual(len(dup), 1)
        self.assertEqual(set(dup.move_ids.ids), {a.id, b.id})
        action = dup.action_open_documents()
        self.assertEqual(action["res_model"], "account.move")

    def test_date_out_of_order(self):
        self._invoice(name="ORD/2026/00001", date=self.today - timedelta(days=10))
        self._invoice(name="ORD/2026/00002", date=self.today - timedelta(days=30))
        wizard = self._wizard()
        wizard.action_check()
        bad = wizard.line_ids.filtered(
            lambda l: l.kind == "date_order" and l.prefix == "ORD/2026/")
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad.number, 2)
        # and it can be switched off
        quiet = self._wizard(check_date_order=False)
        quiet.action_check()
        self.assertEqual(quiet.date_order_count, 0)

    def test_prefixes_are_independent(self):
        year = self.today.year
        self._invoice(name="A/%s/00001" % year)
        self._invoice(name="A/%s/00002" % year)
        self._invoice(name="B/%s/00050" % year)
        wizard = self._wizard()
        wizard.action_check()
        # The jump from A/00002 to B/00050 is a change of prefix, not a gap.
        self.assertEqual(wizard.gap_count, 0)

    def test_drafts_excluded_by_default(self):
        self._invoice(name="DRF/2026/00001")
        self._invoice(name="DRF/2026/00003")
        draft = self._invoice(post=False)
        wizard = self._wizard()
        wizard.action_check()
        self.assertNotIn(draft.id, wizard.line_ids.move_ids.ids)
        self.assertEqual(
            wizard.line_ids.filtered(lambda l: l.prefix == "DRF/2026/").mapped("number"), [2])

    def test_date_validation(self):
        with self.assertRaises(UserError):
            self._wizard(date_from=self.today, date_to=self.today - timedelta(days=5))
