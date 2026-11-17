import re

from odoo import fields, models

# "INV/2026/00123" -> prefix "INV/2026/", number 123, width 5
SEQUENCE_RE = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")


def split_name(name):
    """Split a document name into its prefix and trailing number.

    Returns (prefix, number, width) or None when the name does not end in
    digits, which is the case for manually typed references.
    """
    if not name:
        return None
    match = SEQUENCE_RE.match(name.strip())
    if not match:
        return None
    digits = match.group("number")
    return match.group("prefix"), int(digits), len(digits)


class MnaSequenceGap(models.TransientModel):
    _name = "mna.sequence.gap"
    _description = "Sequence Finding"
    _order = "prefix, number, id"

    wizard_id = fields.Many2one("mna.sequence.gap.wizard", required=True, ondelete="cascade")
    journal_id = fields.Many2one("account.journal", readonly=True)
    prefix = fields.Char(readonly=True)
    number = fields.Integer(readonly=True)
    expected_name = fields.Char(string="Document", readonly=True)
    kind = fields.Selection(
        [
            ("gap", "Missing"),
            ("duplicate", "Duplicated"),
            ("date_order", "Date Out Of Order"),
        ],
        readonly=True,
    )
    detail = fields.Char(readonly=True)
    move_ids = fields.Many2many("account.move", string="Documents", readonly=True)

    def action_open_documents(self):
        self.ensure_one()
        if not self.move_ids:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.expected_name,
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.move_ids.ids)],
            "target": "current",
        }
