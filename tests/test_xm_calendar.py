"""Check screenshot-derived XM GOLD sessions WITHOUT trusting historical timezone."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from smc_agent.xm_calendar import (
    XM_GOLD_DISPLAYED, DisplayedDay, XMGoldDisplayedSchedule,
    schedule_snapshot
)
from smc_agent.paper import SessionWindow, PaperAssumptions, replay_market_next_open
from smc_agent.lifecycle import PublishedSignal
from smc_agent.quotes import QuoteBar, QuoteHistory


class CalendarScreenshotTests(unittest.TestCase):
    def test_monday_thursday_hours_from_image(self):
        for day in (0, 1, 2, 3):
            d = XM_GOLD_DISPLAYED.observed_days[day]
            self.assertEqual((d.quote_open, d.quote_close), ("01:00", "23:59"))
            self.assertEqual((d.trade_open, d.trade_close), ("01:02", "23:58"))
            self.assertEqual(d.research_trade_window(), SessionWindow(62, 1438))

    def test_friday_quotation_closes_one_minute_earlier(self):
        friday = XM_GOLD_DISPLAYED.observed_days[4]
        self.assertEqual((friday.quote_open, friday.quote_close), ("01:00", "23:58"))
        self.assertEqual((friday.trade_open, friday.trade_close), ("01:02", "23:58"))

    def test_weekend_has_no_displayed_trading_sessions(self):
        for day in (5, 6):
            d = XM_GOLD_DISPLAYED.observed_days[day]
            self.assertIsNone(d.quote_open)
            self.assertIsNone(d.trade_open)
            self.assertIsNone(d.research_trade_window())

    def test_contract_and_source_provenance(self):
        self.assertEqual(XM_GOLD_DISPLAYED.symbol, "GOLD")
        self.assertEqual(XM_GOLD_DISPLAYED.venue, "XMGlobal-MT5 5 (demo)")
        self.assertEqual(XM_GOLD_DISPLAYED.screenshot_received_on, date(2026, 11, 25))
        report = schedule_snapshot()
        self.assertFalse(report["historical_paper_trading_allowed"])
        self.assertEqual(report["historical_validity"], "UNVERIFIED")
        self.assertEqual(report["display_clock_utc_offset"], "UNVERIFIED")
        self.assertEqual(report["broker_orders_sent"], 0)

    def test_conversion_never_assumes_timezone(self):
        cal = XM_GOLD_DISPLAYED.as_unverified_paper_calendar()
        self.assertIsNone(cal.verified_server_utc_offset_minutes)
        self.assertEqual(cal.weekdays[0], (SessionWindow(62, 1438),))
        self.assertEqual(cal.weekdays[5], ())
        monday = datetime(2026, 11, 23, 12, 5, tzinfo=timezone.utc)
        self.assertEqual(cal.status(monday, monday+timedelta(minutes=5)), "UNVERIFIED")
        june = datetime(2026, 6, 22, 12, 5, tzinfo=timezone.utc)
        self.assertEqual(cal.status(june, june+timedelta(minutes=5)), "UNVERIFIED")

    def test_paper_replay_blocks_target_even_if_ohlc_touches_it(self):
        venue = XM_GOLD_DISPLAYED.venue
        symbol = XM_GOLD_DISPLAYED.symbol
        base = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
        def quote(minute, bid_o, bid_h, bid_l, bid_c):
            opening = base+timedelta(minutes=minute)
            return QuoteBar(opening, opening+timedelta(minutes=5),
                bid_o, bid_h, bid_l, bid_c,
                bid_o+0.2, bid_h+0.2, bid_l+0.2, bid_c+0.2)
        history = QuoteHistory(venue, symbol, "FABRICATED_FOR_TESTS", (
            quote(5, 4000, 4000.5, 3999.8, 4000.1),
            quote(10, 4000.1, 4003.0, 3999.9, 4002.5),
        ))
        alert = PublishedSignal("example", venue, symbol,
            base+timedelta(minutes=2), "buy", 4000.2, 3999.0, 4002.0)
        model = PaperAssumptions(
            risk_budget_usd=Decimal("5"),
            extra_loss_reserve_usd=Decimal("1"),
            commission_roundtrip_usd_per_lot=Decimal("10"),
            slippage_each_side_price=Decimal(".02"),
            max_entry_drift_price=Decimal(".50"),
            max_open_spread_pct=Decimal(".10")
        )
        result = replay_market_next_open(
            alert, history,
            sessions=XM_GOLD_DISPLAYED.as_unverified_paper_calendar(),
            assumptions=model,
            as_of=base+timedelta(minutes=15))
        self.assertEqual(result.status, "SESSION_UNVERIFIED")
        self.assertIsNone(result.modeled_net_usd)
        self.assertEqual(result.orders_sent, 0)
        self.assertFalse(result.broker_fills_verified)

    def test_reject_invalid_clock_and_partial_weekdays(self):
        with self.assertRaises(ValueError):
            DisplayedDay("01:00", "23:59", "01:02", None)
        with self.assertRaises(ValueError):
            DisplayedDay("01:00", "00:59", "01:02", "23:58")
        with self.assertRaises(ValueError):
            DisplayedDay("01:00", "23:59", "00:59", "23:58")
        with self.assertRaises(ValueError):
            DisplayedDay("24:01", "23:59", "01:02", "23:58")
        with self.assertRaises(ValueError):
            replace(XM_GOLD_DISPLAYED, observed_days={0: XM_GOLD_DISPLAYED.observed_days[0]})

    def test_unknown_session_still_blocks_out_of_sample(self):
        cal = XM_GOLD_DISPLAYED.as_unverified_paper_calendar()
        summer = datetime(2026, 7, 20, 15, tzinfo=timezone.utc)
        winter = datetime(2026, 12, 21, 15, tzinfo=timezone.utc)
        self.assertEqual(cal.status(summer, summer+timedelta(minutes=5)), "UNVERIFIED")
        self.assertEqual(cal.status(winter, winter+timedelta(minutes=5)), "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
