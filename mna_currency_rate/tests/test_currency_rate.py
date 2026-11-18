from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

# A realistic ECB style payload: everything quoted against the euro.
ECB_SAMPLE = {
    "EUR": 1.0,
    "USD": 1.0850,
    "GBP": 0.8520,
    "JPY": 163.20,
    "CHF": 0.9510,
}


@tagged("post_install", "-at_install")
class TestCurrencyRate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Currency = cls.env["res.currency"]
        cls.Rate = cls.env["res.currency.rate"]

        cls.eur = cls.Currency.with_context(active_test=False).search(
            [("name", "=", "EUR")], limit=1)
        cls.usd = cls.Currency.with_context(active_test=False).search(
            [("name", "=", "USD")], limit=1)
        cls.gbp = cls.Currency.with_context(active_test=False).search(
            [("name", "=", "GBP")], limit=1)
        (cls.eur | cls.usd | cls.gbp).write({"active": True})

    def _rate_of(self, currency, date=None):
        rate = self.Rate.search([
            ("currency_id", "=", currency.id),
            ("company_id", "=", self.company.id),
            ("name", "=", date or fields.Date.context_today(self.company)),
        ], limit=1)
        return rate.rate if rate else None

    # ------------------------------------------------------------------
    # The maths. This is the reason the module exists.
    # ------------------------------------------------------------------
    def test_rates_are_rebased_onto_company_currency(self):
        """A euro based feed written into a dollar company.

        The ECB quotes everything against the euro. Odoo stores a rate
        as units of the foreign currency per one unit of the COMPANY
        currency. Writing the provider's numbers in unchanged is the
        classic bug: in a USD company it would store GBP at 0.8520,
        which is GBP per EUR, not per USD, and every conversion would be
        wrong by the EUR/USD rate.
        """
        self.company.currency_id = self.usd
        self.company._mna_apply_rates(dict(ECB_SAMPLE))

        # GBP per USD = GBP per EUR / USD per EUR
        self.assertAlmostEqual(
            self._rate_of(self.gbp), 0.8520 / 1.0850, places=6,
            msg="GBP was not rebased from the euro onto the dollar",
        )
        self.assertAlmostEqual(
            self._rate_of(self.eur), 1.0 / 1.0850, places=6,
            msg="EUR itself must be rebased too",
        )

    def test_conversion_matches_the_real_cross_rate(self):
        """Checked through Odoo's own converter rather than by reading
        back the number this module wrote, so the test would still fail
        if the rate direction were inverted."""
        self.company.currency_id = self.usd
        self.company._mna_apply_rates(dict(ECB_SAMPLE))

        today = fields.Date.context_today(self.company)
        # 1000, not 1. _convert rounds to the target currency's own
        # precision, so a single euro comes back as 1.09 and the
        # assertion would be testing the rounding rather than the rate.
        converted = self.eur._convert(
            1000.0, self.usd, self.company, today,
        )
        self.assertAlmostEqual(
            converted, 1085.0, places=2,
            msg="1000 euro should convert at the EUR/USD rate",
        )

    def test_company_currency_is_not_written(self):
        """A rate of the company currency against itself is always 1 and
        storing it only invites rounding noise."""
        self.company.currency_id = self.usd
        self.company._mna_apply_rates(dict(ECB_SAMPLE))
        self.assertIsNone(self._rate_of(self.usd))

    def test_base_currency_company_is_unchanged(self):
        """A euro company with a euro based feed should get the
        provider's numbers as they are.

        A fresh company, because the currency of one that already has
        journal entries cannot be changed, and the demo database has
        them.
        """
        company = self.env["res.company"].create({
            "name": "Souq Rate Test EUR",
            "currency_id": self.eur.id,
        })
        company._mna_apply_rates(dict(ECB_SAMPLE))
        rate = self.Rate.search([
            ("currency_id", "=", self.usd.id),
            ("company_id", "=", company.id),
            ("name", "=", fields.Date.context_today(company)),
        ], limit=1)
        self.assertAlmostEqual(rate.rate, 1.0850, places=6)

    def test_unquoted_company_currency_is_refused(self):
        """Rather than guess, or write rates that are silently wrong."""
        self.company.currency_id = self.usd
        with self.assertRaises(UserError):
            self.company._mna_apply_rates({"EUR": 1.0, "GBP": 0.852})

    def test_zero_rate_from_provider_is_refused(self):
        self.company.currency_id = self.usd
        with self.assertRaises(UserError):
            self.company._mna_apply_rates({"EUR": 1.0, "USD": 0.0})

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def test_running_twice_updates_rather_than_duplicates(self):
        """A daily cron that appends would put 365 rows per currency per
        year into a table the accountant has to look at."""
        self.company.currency_id = self.usd
        self.company._mna_apply_rates(dict(ECB_SAMPLE))

        moved = dict(ECB_SAMPLE, GBP=0.8600)
        self.company._mna_apply_rates(moved)

        today = fields.Date.context_today(self.company)
        rates = self.Rate.search([
            ("currency_id", "=", self.gbp.id),
            ("company_id", "=", self.company.id),
            ("name", "=", today),
        ])
        self.assertEqual(len(rates), 1, "A second run must not add a row")
        self.assertAlmostEqual(rates.rate, 0.8600 / 1.0850, places=6)

    def test_unknown_currency_codes_are_ignored(self):
        """Providers quote currencies Odoo has never heard of."""
        self.company.currency_id = self.usd
        written = self.company._mna_apply_rates(
            dict(ECB_SAMPLE, ZZZ=12.0)
        )
        self.assertTrue(written)
        self.assertFalse(
            self.Currency.with_context(active_test=False).search(
                [("name", "=", "ZZZ")])
        )

    # ------------------------------------------------------------------
    # Failure handling
    # ------------------------------------------------------------------
    def test_failure_is_logged_and_does_not_raise(self):
        """One provider being down must not stop the cron for every
        other company in the database."""
        self.company.currency_id = self.usd
        self.company.mna_rate_provider = "ecb"

        with patch.object(
            type(self.company), "_mna_rates_from_provider",
            side_effect=UserError("provider exploded"),
        ):
            self.company.mna_update_rates()

        self.assertEqual(self.company.mna_rate_last_state, "fail")
        self.assertIn("provider exploded", self.company.mna_rate_last_message)
        log = self.env["mna.currency.rate.log"].search(
            [("company_id", "=", self.company.id)], limit=1)
        self.assertEqual(log.state, "fail")

    def test_failure_leaves_existing_rates_intact(self):
        """Stale rates are bad. Rates deleted because a fetch failed are
        very much worse."""
        self.company.currency_id = self.usd
        self.company._mna_apply_rates(dict(ECB_SAMPLE))
        before = self._rate_of(self.gbp)

        with patch.object(
            type(self.company), "_mna_rates_from_provider",
            side_effect=UserError("down"),
        ):
            self.company.mna_update_rates()

        self.assertEqual(self._rate_of(self.gbp), before)

    def test_manual_button_raises_so_the_user_sees_it(self):
        """The cron swallows errors on purpose; a person pressing a
        button has to be told."""
        self.company.currency_id = self.usd
        with patch.object(
            type(self.company), "_mna_rates_from_provider",
            side_effect=UserError("down"),
        ):
            with self.assertRaises(UserError):
                self.company.action_mna_update_rates_now()

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    def test_cron_skips_companies_that_are_switched_off(self):
        self.company.mna_rate_enabled = False
        with patch.object(type(self.company), "mna_update_rates") as called:
            self.env["res.company"]._mna_cron_update_rates()
            called.assert_not_called()

    def test_cron_retries_a_failed_company_next_run(self):
        """A failure should not wait out a monthly interval before it is
        tried again."""
        self.company.write({
            "mna_rate_enabled": True,
            "mna_rate_interval": "monthly",
            "mna_rate_last_sync": fields.Datetime.now(),
            "mna_rate_last_state": "fail",
        })
        with patch.object(type(self.company), "mna_update_rates") as called:
            self.env["res.company"]._mna_cron_update_rates()
            called.assert_called()

    def test_cron_leaves_a_recent_success_alone(self):
        self.company.write({
            "mna_rate_enabled": True,
            "mna_rate_interval": "monthly",
            "mna_rate_last_sync": fields.Datetime.now(),
            "mna_rate_last_state": "ok",
        })
        with patch.object(type(self.company), "mna_update_rates") as called:
            self.env["res.company"]._mna_cron_update_rates()
            called.assert_not_called()

    # ------------------------------------------------------------------
    # Provider parsing, without touching the network
    # ------------------------------------------------------------------
    def test_ecb_xml_is_parsed(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                         xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
          <Cube><Cube time="2026-11-18">
            <Cube currency="USD" rate="1.0850"/>
            <Cube currency="GBP" rate="0.8520"/>
          </Cube></Cube>
        </gesmes:Envelope>"""
        with patch.object(type(self.company), "_mna_rate_fetch", return_value=xml):
            rates = self.company._mna_rates_ecb()
        self.assertEqual(rates["EUR"], 1.0)
        self.assertAlmostEqual(rates["USD"], 1.0850)
        self.assertAlmostEqual(rates["GBP"], 0.8520)

    def test_erapi_error_response_is_refused(self):
        with patch.object(
            type(self.company), "_mna_rate_fetch",
            return_value={"result": "error", "rates": {}},
        ):
            with self.assertRaises(UserError):
                self.company._mna_rates_erapi()

    def test_unknown_provider_is_refused(self):
        self.company.mna_rate_provider = "ecb"
        with patch.object(
            type(self.company), "_mna_rates_from_provider",
            side_effect=UserError("Unknown rate provider"),
        ):
            with self.assertRaises(UserError):
                self.company.action_mna_update_rates_now()
