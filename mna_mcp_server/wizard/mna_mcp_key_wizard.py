from odoo import fields, models


class MnaMcpKeyWizard(models.TransientModel):
    _name = "mna.mcp.key.wizard"
    _description = "Generate MCP API Key"

    name = fields.Char(string="Description", required=True)
    user_id = fields.Many2one(
        "res.users", string="Runs As", required=True, default=lambda self: self.env.user
    )
    expiration_date = fields.Datetime()
    key = fields.Char(readonly=True)

    def action_generate(self):
        self.ensure_one()
        _record, key = self.env["mna.mcp.key"]._generate(
            self.name, self.user_id, self.expiration_date
        )
        self.key = key
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
