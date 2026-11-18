from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mna_rate_enabled = fields.Boolean(
        related="company_id.mna_rate_enabled", readonly=False,
    )
    mna_rate_provider = fields.Selection(
        related="company_id.mna_rate_provider", readonly=False,
    )
    mna_rate_interval = fields.Selection(
        related="company_id.mna_rate_interval", readonly=False,
    )
    mna_rate_last_sync = fields.Datetime(
        related="company_id.mna_rate_last_sync", readonly=True,
    )
    mna_rate_last_state = fields.Selection(
        related="company_id.mna_rate_last_state", readonly=True,
    )
    mna_rate_last_message = fields.Char(
        related="company_id.mna_rate_last_message", readonly=True,
    )

    def action_mna_update_rates_now(self):
        self.ensure_one()
        return self.company_id.action_mna_update_rates_now()
