import logging
from datetime import timedelta
from xml.etree import ElementTree

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

TIMEOUT = 20

PROVIDERS = [
    ("ecb", "European Central Bank"),
    ("frankfurter", "Frankfurter (ECB mirror)"),
    ("erapi", "Open Exchange Rates API"),
]


class ResCompany(models.Model):
    _inherit = "res.company"

    mna_rate_enabled = fields.Boolean(
        string="Update rates automatically",
        help="Fetch exchange rates on a schedule from a free provider.",
    )
    mna_rate_provider = fields.Selection(
        selection=PROVIDERS,
        string="Rate provider",
        default="ecb",
    )
    mna_rate_interval = fields.Selection(
        selection=[
            ("daily", "Daily"),
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
        ],
        string="Update frequency",
        default="daily",
    )
    mna_rate_last_sync = fields.Datetime(
        string="Last update", readonly=True,
    )
    mna_rate_last_state = fields.Selection(
        selection=[("ok", "Success"), ("fail", "Failed")],
        string="Last result", readonly=True,
    )
    mna_rate_last_message = fields.Char(
        string="Last message", readonly=True,
    )

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------
    def _mna_rate_fetch(self, url, as_json=True):
        """One place for the HTTP call, so a provider that is down or
        slow cannot hang the cron for every other company."""
        import requests

        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json() if as_json else response.content

    def _mna_rates_ecb(self):
        """The ECB daily reference rates, quoted against the euro."""
        data = self._mna_rate_fetch(
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
            as_json=False,
        )
        root = ElementTree.fromstring(data)
        rates = {"EUR": 1.0}
        for node in root.iter():
            code = node.attrib.get("currency")
            rate = node.attrib.get("rate")
            if code and rate:
                rates[code] = float(rate)
        return rates

    def _mna_rates_frankfurter(self):
        data = self._mna_rate_fetch("https://api.frankfurter.app/latest?from=EUR")
        rates = dict(data.get("rates") or {})
        rates["EUR"] = 1.0
        return rates

    def _mna_rates_erapi(self):
        data = self._mna_rate_fetch("https://open.er-api.com/v6/latest/USD")
        if data.get("result") != "success":
            raise UserError(_("The provider returned an error response."))
        rates = dict(data.get("rates") or {})
        rates["USD"] = 1.0
        return rates

    def _mna_rates_from_provider(self):
        """Rates keyed by ISO code, in whatever base the provider uses.

        The base does not matter to the caller: _mna_apply_rates rebases
        everything onto the company currency.
        """
        self.ensure_one()
        provider = self.mna_rate_provider or "ecb"
        getter = getattr(self, "_mna_rates_%s" % provider, None)
        if not getter:
            raise UserError(_("Unknown rate provider: %s") % provider)
        rates = getter()
        if not rates:
            raise UserError(_("The provider returned no rates."))
        return rates

    # ------------------------------------------------------------------
    # Applying
    # ------------------------------------------------------------------
    def _mna_apply_rates(self, provider_rates, rate_date=None):
        """Write the rates, rebased onto this company's currency.

        This is the part that is usually wrong elsewhere. Providers
        publish against their own base: the ECB against the euro, most
        JSON feeds against the dollar. Odoo stores a rate as units of
        the foreign currency per one unit of the COMPANY currency. So a
        euro-based feed written straight into a dollar company makes
        every conversion wrong by the EUR/USD rate.

        Dividing each rate by the company currency's own rate in the
        same base rebases the whole set, whatever base it arrived in.
        """
        self.ensure_one()
        rate_date = rate_date or fields.Date.context_today(self)

        own_code = self.currency_id.name
        own_rate = provider_rates.get(own_code)
        if not own_rate:
            raise UserError(_(
                "The provider does not quote %s, so the rates cannot be "
                "converted to this company's currency."
            ) % own_code)
        if float_is_zero(own_rate, precision_digits=12):
            raise UserError(_("The provider quoted %s as zero.") % own_code)

        Currency = self.env["res.currency"]
        Rate = self.env["res.currency.rate"]

        # Only currencies that are actually in use. Writing rates for
        # the full ISO list would add hundreds of rows a day that nobody
        # reads.
        currencies = Currency.search([("name", "in", list(provider_rates))])

        written = 0
        for currency in currencies:
            if currency == self.currency_id:
                continue
            value = provider_rates[currency.name] / own_rate
            if float_is_zero(value, precision_digits=12):
                continue

            existing = Rate.search([
                ("currency_id", "=", currency.id),
                ("company_id", "=", self.id),
                ("name", "=", rate_date),
            ], limit=1)
            if existing:
                existing.rate = value
            else:
                Rate.create({
                    "currency_id": currency.id,
                    "company_id": self.id,
                    "name": rate_date,
                    "rate": value,
                })
            written += 1

        return written

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    def mna_update_rates(self, raise_on_error=False):
        """Fetch and apply for each company in self.

        Failures are recorded rather than raised by default: one
        provider being down must not stop the other companies, and it
        must never leave the previous good rates damaged.
        """
        Log = self.env["mna.currency.rate.log"]

        for company in self:
            try:
                rates = company._mna_rates_from_provider()
                written = company._mna_apply_rates(rates)
            except Exception as error:  # noqa: BLE001 - recorded below
                message = str(error).strip() or error.__class__.__name__
                _logger.warning(
                    "Currency rate update failed for %s: %s",
                    company.display_name, message,
                )
                company.write({
                    "mna_rate_last_sync": fields.Datetime.now(),
                    "mna_rate_last_state": "fail",
                    "mna_rate_last_message": message[:255],
                })
                Log.sudo().create({
                    "company_id": company.id,
                    "provider": company.mna_rate_provider,
                    "state": "fail",
                    "message": message[:255],
                })
                if raise_on_error:
                    raise
                continue

            company.write({
                "mna_rate_last_sync": fields.Datetime.now(),
                "mna_rate_last_state": "ok",
                "mna_rate_last_message": _("%s rates updated") % written,
            })
            Log.sudo().create({
                "company_id": company.id,
                "provider": company.mna_rate_provider,
                "state": "ok",
                "rate_count": written,
                "message": _("%s rates updated") % written,
            })
        return True

    def action_mna_update_rates_now(self):
        """Button. Raises, because someone is watching and wants to know."""
        self.ensure_one()
        self.mna_update_rates(raise_on_error=True)
        return True

    @api.model
    def _mna_cron_update_rates(self):
        """Called by the scheduled action.

        Each company carries its own frequency, so the cron runs daily
        and skips the companies that are not due yet. That keeps one
        scheduled action for the whole database.
        """
        companies = self.search([("mna_rate_enabled", "=", True)])
        now = fields.Datetime.now()
        gap = {"daily": 1, "weekly": 7, "monthly": 30}

        due = self.browse()
        for company in companies:
            last = company.mna_rate_last_sync
            days = gap.get(company.mna_rate_interval or "daily", 1)
            # A failed run is retried on the next cron rather than
            # waiting out the full interval, because a stale rate is
            # worse than an extra request.
            if (not last
                    or company.mna_rate_last_state == "fail"
                    or last <= now - timedelta(days=days)):
                due |= company

        if due:
            due.mna_update_rates()
        return True
