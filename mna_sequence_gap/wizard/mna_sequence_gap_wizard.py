from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.mna_sequence_gap import split_name


class MnaSequenceGapWizard(models.TransientModel):
    _name = "mna.sequence.gap.wizard"
    _description = "Sequence Gap & Duplicate Report"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    journal_ids = fields.Many2many(
        "account.journal",
        string="Journals",
        domain="[('company_id', '=', company_id)]",
        help="Leave empty to check every journal of the company.",
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1),
    )
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    include_draft = fields.Boolean(
        string="Include Drafts",
        help="Drafts have no final number yet, so they are normally left out.",
    )
    check_date_order = fields.Boolean(string="Check Date Order", default=True)

    line_ids = fields.One2many("mna.sequence.gap", "wizard_id", readonly=True)
    gap_count = fields.Integer(compute="_compute_counts")
    duplicate_count = fields.Integer(compute="_compute_counts")
    date_order_count = fields.Integer(compute="_compute_counts")
    checked_count = fields.Integer(readonly=True, string="Documents Checked")
    has_run = fields.Boolean(readonly=True)

    @api.depends("line_ids.kind")
    def _compute_counts(self):
        for wizard in self:
            kinds = wizard.line_ids.mapped("kind")
            wizard.gap_count = kinds.count("gap")
            wizard.duplicate_count = kinds.count("duplicate")
            wizard.date_order_count = kinds.count("date_order")

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise UserError(_("The start date must come before the end date."))

    # ------------------------------------------------------------------
    def _moves(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ]
        if self.journal_ids:
            domain.append(("journal_id", "in", self.journal_ids.ids))
        if self.include_draft:
            domain.append(("state", "!=", "cancel"))
        else:
            domain.append(("state", "=", "posted"))
        return self.env["account.move"].search(domain, order="name asc, id asc")

    def _findings(self, moves):
        """Group documents by sequence prefix and report what is wrong."""
        self.ensure_one()
        # (journal, prefix) -> {number: [moves]}
        grouped = defaultdict(lambda: defaultdict(list))
        widths = {}
        for move in moves:
            parts = split_name(move.name)
            if not parts:
                continue
            prefix, number, width = parts
            key = (move.journal_id, prefix)
            grouped[key][number].append(move)
            widths[key] = max(widths.get(key, 0), width)

        findings = []
        for (journal, prefix), numbers in grouped.items():
            width = widths[(journal, prefix)]
            present = sorted(numbers)
            if not present:
                continue
            base = {
                "wizard_id": self.id,
                "journal_id": journal.id,
                "prefix": prefix,
            }

            # Gaps between the lowest and highest number actually used.
            missing = set(range(present[0], present[-1] + 1)) - set(present)
            for number in sorted(missing):
                findings.append(dict(
                    base,
                    number=number,
                    expected_name="%s%0*d" % (prefix, width, number),
                    kind="gap",
                    detail=_("No document carries this number."),
                ))

            # The same number used more than once.
            for number in present:
                moves_here = numbers[number]
                if len(moves_here) > 1:
                    findings.append(dict(
                        base,
                        number=number,
                        expected_name=moves_here[0].name,
                        kind="duplicate",
                        detail=_("Used by %s documents.", len(moves_here)),
                        move_ids=[(6, 0, [m.id for m in moves_here])],
                    ))

            # A higher number carrying an earlier date than the one before it.
            if self.check_date_order:
                previous_move = None
                for number in present:
                    move = numbers[number][0]
                    if previous_move and move.date < previous_move.date:
                        findings.append(dict(
                            base,
                            number=number,
                            expected_name=move.name,
                            kind="date_order",
                            detail=_(
                                "Dated %(this)s, after %(prev_name)s dated %(prev)s.",
                                this=move.date, prev_name=previous_move.name,
                                prev=previous_move.date,
                            ),
                            move_ids=[(6, 0, [move.id, previous_move.id])],
                        ))
                    previous_move = move
        return findings

    def action_check(self):
        self.ensure_one()
        self.line_ids.unlink()
        moves = self._moves()
        self.checked_count = len(moves)
        findings = self._findings(moves)
        if findings:
            self.env["mna.sequence.gap"].create(findings)
        self.has_run = True
        return {
            "type": "ir.actions.act_window",
            "name": _("Sequence Check"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
