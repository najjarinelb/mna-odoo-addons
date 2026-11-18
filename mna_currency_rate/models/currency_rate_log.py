from odoo import fields, models


class CurrencyRateLog(models.Model):
    _name = "mna.currency.rate.log"
    _description = "Currency Rate Update Log"
    _order = "create_date desc, id desc"
    _rec_name = "create_date"

    # A provider that quietly started failing three weeks ago is the
    # failure mode worth catching: the rates simply stop moving and
    # nobody notices until a month end looks wrong. A log row per run
    # makes that visible.
    company_id = fields.Many2one(
        "res.company", string="Company", required=True, ondelete="cascade",
    )
    provider = fields.Char(string="Provider", readonly=True)
    state = fields.Selection(
        selection=[("ok", "Success"), ("fail", "Failed")],
        string="Result", readonly=True,
    )
    rate_count = fields.Integer(string="Rates written", readonly=True)
    message = fields.Char(string="Message", readonly=True)
