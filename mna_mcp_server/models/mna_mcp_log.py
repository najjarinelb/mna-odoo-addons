from odoo import fields, models


class MnaMcpLog(models.Model):
    _name = "mna.mcp.log"
    _description = "MCP Call Log"
    _order = "id desc"

    create_date = fields.Datetime(string="Date", readonly=True)
    user_id = fields.Many2one("res.users", readonly=True, ondelete="set null")
    key_id = fields.Many2one("mna.mcp.key", readonly=True, ondelete="set null")
    tool = fields.Char(readonly=True)
    model = fields.Char(readonly=True)
    arguments = fields.Text(readonly=True)
    success = fields.Boolean(readonly=True)
    error = fields.Text(readonly=True)
