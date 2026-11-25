"""Session-aware PAPER replay tests, with ONLY FABRICATED bid/ask quotes."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from smc_agent.lifecycle import PublishedSignal
from smc_agent.quotes import QuoteBar, QuoteHistory
from smc_agent.paper import (
    SessionWindow, TradingSessions, PaperAssumptions, replay_market_next_open
)

BASE = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
VENUE = "XMGlobal-MT5 5 (demo)"
SYMBOL = "GOLD"


def bar(minute, o=4000., h=4000.5, l=3999.8, c=4000.1, spread=.2):
    start = BASE + timedelta(minutes=minute)
    return QuoteBar(start, start+timedelta(minutes=5),
                    o, h, l, c, o+spread, h+spread, l+spread, c+spread)


def plan(side="buy", **kwargs):
    values = dict(signal_id="synthetic-paper-1", venue=VENUE, symbol=SYMBOL,
                  published_at=BASE+timedelta(minutes=2), side=side,
                  entry=4000.20 if side == "buy" else 4000.00,
                  stop=3999.00 if side == "buy" else 4001.00,
                  target=4002.00 if side == "buy" else 3998.00)
    values.update(kwargs)
    return PublishedSignal(**values)


def assumptions(**kwargs):
    values = dict(risk_budget_usd=Decimal("5.00"),
                  extra_loss_reserve_usd=Decimal("1.00"),
                  commission_roundtrip_usd_per_lot=Decimal("10"),
                  slippage_each_side_price=Decimal(".02"),
                  max_entry_drift_price=Decimal(".50"),
                  max_open_spread_pct=Decimal(".10"))
    values.update(kwargs)
    return PaperAssumptions(**values)


def sessions(**kwargs):
    values = dict(verified_server_utc_offset_minutes=0,
                  weekdays={0: (SessionWindow(0, 1439),)})
    values.update(kwargs)
    return TradingSessions(**values)


def run(bars, *, intent=None, trading=None, policy=None, cutoff=50):
    return replay_market_next_open(
        intent or plan(),
        QuoteHistory(VENUE, SYMBOL, "FABRICATED_TEST_QUOTES", tuple(bars)),
        sessions=trading or sessions(), assumptions=policy or assumptions(),
        as_of=BASE+timedelta(minutes=cutoff))


class SessionTests(unittest.TestCase):
    def test_monday_known_and_other_weekday_unknown(self):
        calendar=sessions()
        self.assertEqual(calendar.status(BASE,BASE+timedelta(minutes=5)), "OPEN")
        self.assertEqual(calendar.status(
            BASE+timedelta(days=1),BASE+timedelta(days=1,minutes=5)),
            "UNVERIFIED")

    def test_unknown_offset_is_not_assumed(self):
        calendar=sessions(verified_server_utc_offset_minutes=None)
        self.assertEqual(calendar.status(BASE, BASE+timedelta(minutes=5)),
                         "UNVERIFIED")

    def test_explicit_verified_closed(self):
        cal=sessions(weekdays={0: ()})
        self.assertEqual(cal.status(BASE,BASE+timedelta(minutes=5)), "CLOSED")

    def test_session_overlap_refused(self):
        with self.assertRaises(ValueError):
            sessions(weekdays={0:(SessionWindow(0,600),SessionWindow(599,900))})

    def test_wrong_offset_rejected(self):
        with self.assertRaises(ValueError):
            sessions(verified_server_utc_offset_minutes=900)

    def test_midnight_boundary_is_not_silently_assumed_open(self):
        start=BASE+timedelta(hours=11,minutes=58)
        cal=sessions()
        self.assertEqual(cal.status(start,start+timedelta(minutes=5)),
                         "UNVERIFIED")

    def test_half_open_session_closing_time(self):
        cal=sessions(weekdays={0:(SessionWindow(720,730),)})
        self.assertEqual(cal.status(BASE+timedelta(minutes=5),
                                    BASE+timedelta(minutes=10)), "OPEN")
        self.assertEqual(cal.status(BASE+timedelta(minutes=10),
                                    BASE+timedelta(minutes=15)), "CLOSED")


class PaperTests(unittest.TestCase):
    def test_long_paper_target_costs_and_size(self):
        result=run([bar(5),bar(10,o=4000.1,h=4003,l=3999.9,c=4002.5)])
        self.assertEqual(result.status,"PAPER_TARGET_MODEL")
        self.assertIsNotNone(result.modeled_net_usd)
        self.assertGreater(result.modeled_net_usd,0)
        self.assertEqual(result.broker_fills_verified,False)
        self.assertEqual(result.orders_sent,0)
        self.assertEqual(result.modeled_fees_usd,
                         result.paper_lots*Decimal("10"))
        self.assertLess(result.modeled_net_usd,result.modeled_gross_usd)
        self.assertEqual(result.paper_entry_price,Decimal("4000.22"))
        self.assertEqual(result.paper_exit_price,Decimal("4001.98"))

    def test_long_paper_stop_loss_bounded_only_in_model(self):
        result=run([bar(5),bar(10,o=4000.1,h=4000.4,l=3998.5,c=3998.8)])
        self.assertEqual(result.status,"PAPER_STOP_MODEL")
        self.assertLess(result.modeled_net_usd,0)
        self.assertLessEqual(-result.modeled_net_usd+Decimal("1"),
                             Decimal("5.00"))
        self.assertFalse(result.broker_fills_verified)

    def test_short_paper_target_uses_ask_exit(self):
        result=run([bar(5),bar(10,o=3999.6,h=4000.1,l=3997.1,c=3997.5)],
                   intent=plan("sell"))
        self.assertEqual(result.status,"PAPER_TARGET_MODEL")
        self.assertGreater(result.modeled_net_usd,0)
        self.assertEqual(result.paper_entry_price,Decimal("3999.98"))
        self.assertEqual(result.paper_exit_price,Decimal("3998.02"))

    def test_short_stop_uses_ask(self):
        result=run([bar(5),bar(10,o=4000.1,h=4001.2,l=3999.9,c=4001.1)],
                   intent=plan("sell"))
        self.assertEqual(result.status,"PAPER_STOP_MODEL")
        self.assertLess(result.modeled_net_usd,0)

    def test_touching_both_exit_levels_same_bar_is_ambiguous(self):
        result=run([bar(5,h=4003,l=3998,c=4000)])
        self.assertEqual(result.status,"AMBIGUOUS_INTRA_BAR")
        self.assertIsNone(result.modeled_net_usd)

    def test_short_both_levels_ambiguous(self):
        result=run([bar(5,h=4002,l=3997,c=4000)],intent=plan("sell"))
        self.assertEqual(result.status,"AMBIGUOUS_INTRA_BAR")
        self.assertIsNone(result.modeled_net_usd)

    def test_gap_across_stop_is_not_priced(self):
        result=run([bar(5),bar(10,o=3998,h=3998.5,l=3997,c=3998.2)])
        self.assertEqual(result.status,"GAP_EXIT_UNPRICED")
        self.assertIsNone(result.modeled_net_usd)

    def test_gap_across_target_is_not_priced(self):
        result=run([bar(5),bar(10,o=4003,h=4003.5,l=4002.9,c=4003.1)])
        self.assertEqual(result.status,"GAP_EXIT_UNPRICED")

    def test_unverified_sessions_block_entry(self):
        result=run([bar(5)],trading=sessions(verified_server_utc_offset_minutes=None))
        self.assertEqual(result.status,"SESSION_UNVERIFIED")
        self.assertIsNone(result.paper_lots)

    def test_verified_closed_market_blocks_entry(self):
        result=run([bar(5)],trading=sessions(weekdays={0: ()}))
        self.assertEqual(result.status,"NO_ENTRY_SESSION_CLOSED")

    def test_session_closes_after_paper_entry(self):
        result=run([bar(5),bar(10)],
                   trading=sessions(weekdays={0:(SessionWindow(720,730),)}))
        self.assertEqual(result.status,"SESSION_CLOSED_AFTER_PAPER_ENTRY")
        self.assertIsNone(result.modeled_net_usd)

    def test_spread_too_wide_at_entry(self):
        result=run([bar(5,spread=2.0)],
                   policy=assumptions(max_open_spread_pct=Decimal(".01")))
        self.assertEqual(result.status,"NO_ENTRY_WIDE_SPREAD")

    def test_spread_too_wide_after_paper_entry(self):
        result=run([bar(5),bar(10,spread=2.0)],
                   policy=assumptions(max_open_spread_pct=Decimal(".01")))
        self.assertEqual(result.status,"SPREAD_VETO_AFTER_PAPER_ENTRY")
        self.assertIsNone(result.modeled_net_usd)

    def test_stale_first_bar_refused(self):
        result=run([bar(25)],
                   policy=assumptions(max_entry_wait_seconds=600))
        self.assertEqual(result.status,"NO_ENTRY_STALE_QUOTES")

    def test_noncontinuous_candles_no_exit(self):
        result=run([bar(5),bar(15,o=4000,h=4003,l=3999.7,c=4002)])
        self.assertEqual(result.status,"QUOTE_GAP_UNRESOLVED")
        self.assertIsNone(result.modeled_net_usd)

    def test_price_drift_refused(self):
        result=run([bar(5)],
                   policy=assumptions(max_entry_drift_price=Decimal(".01")))
        self.assertEqual(result.status,"NO_ENTRY_PRICE_DRIFT")

    def test_exit_side_quote_already_beyond_stop_blocks_entry(self):
        # Ask is inside the plan's range; the simultaneous Bid is below
        # the stop. A fabricated stop fill would be unjustified.
        result=run([bar(5)],intent=plan(stop=4000.10))
        self.assertEqual(result.status,"NO_ENTRY_EXIT_QUOTE_OUTSIDE_LEVELS")
        self.assertIsNone(result.modeled_net_usd)

    def test_risk_limit_refused_below_min_lot(self):
        result=run([bar(5)],
                   policy=assumptions(risk_budget_usd=Decimal(".02"),
                                      extra_loss_reserve_usd=Decimal("0")))
        self.assertEqual(result.status,"NO_TRADE_MIN_LOT_RISK")

    def test_cost_reserve_exceeds_budget(self):
        result=run([bar(5)],
                   policy=assumptions(risk_budget_usd=Decimal(".5"),
                                      extra_loss_reserve_usd=Decimal("1")))
        self.assertEqual(result.status,"NO_TRADE_RISK_CAP")

    def test_open_unresolved_is_not_a_win(self):
        result=run([bar(5),bar(10)])
        self.assertEqual(result.status,"PAPER_OPEN_UNRESOLVED")
        self.assertIsNone(result.modeled_net_usd)

    def test_no_closed_future_candle(self):
        result=run([bar(5)],cutoff=9)
        self.assertEqual(result.status,"NO_POST_PUBLICATION_DATA")

    def test_market_pair_different_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"venue mismatch"):
            replay_market_next_open(
                plan(venue="DIFFERENT"),QuoteHistory(VENUE,SYMBOL,"TEST",(bar(5),)),
                sessions=sessions(),assumptions=assumptions(),
                as_of=BASE+timedelta(minutes=20))

    def test_symbol_contract_different_is_rejected(self):
        from smc_agent.xm_gold_risk import XM_GOLD_DEMO_SNAPSHOT
        with self.assertRaisesRegex(ValueError,"unrelated broker contract"):
            replay_market_next_open(
                plan(symbol="SILVER"),QuoteHistory(VENUE,"SILVER","TEST",(bar(5),)),
                sessions=sessions(),assumptions=assumptions(),
                as_of=BASE+timedelta(minutes=20),
                contract=XM_GOLD_DEMO_SNAPSHOT)

    def test_invalid_assumptions(self):
        with self.assertRaises(ValueError):
            assumptions(max_open_spread_pct=Decimal("0"))
        with self.assertRaises(ValueError):
            assumptions(slippage_each_side_price=Decimal("-0.01"))
        with self.assertRaises(ValueError):
            assumptions(quote_bar_seconds=0)

    def test_refuse_missing_monday_assumption(self):
        result=run([bar(5)],trading=sessions(weekdays={}))
        self.assertEqual(result.status,"SESSION_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
