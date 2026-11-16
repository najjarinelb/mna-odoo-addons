from odoo import api, fields, models


class MnaMcpModel(models.Model):
    _name = "mna.mcp.model"
    _description = "MCP Exposed Model"
    _order = "model"

    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    model = fields.Char(related="model_id.model", string="Technical Name", store=True, index=True)
    name = fields.Char(related="model_id.name", string="Description")
    allow_read = fields.Boolean(default=True)
    allow_create = fields.Boolean(default=False)
    allow_write = fields.Boolean(string="Allow Update", default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("model_uniq", "unique(model_id)", "This model is already exposed to MCP."),
    ]

    @api.model
    def _get_rule(self, model_name):
        """Return the allowlist entry for a model, or an empty recordset."""
        return self.sudo().search([("model", "=", model_name)], limit=1)
