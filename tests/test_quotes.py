import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from smc_agent.lifecycle import PublishedSignal
from smc_agent.quotes import QuoteBar, QuoteHistory, load_quote_csv, observe_quotes
from smc_agent.quote_demo import demo

BASE = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_bidask_v04.csv"


def bar(minute, bo=101., bh=103., bl=99., bc=101., spread=.2):
    start = BASE + timedelta(minutes=minute)
    return QuoteBar(start, start+timedelta(minutes=5),
                    bo, bh, bl, bc,
                    bo+spread, bh+spread, bl+spread, bc+spread)


def signal(side="buy", **changes):
    params = dict(signal_id="synthetic-1", venue="SYNTHETIC_ONLY",
                  symbol="TEST_XAUUSD",
                  published_at=BASE+timedelta(minutes=2),
                  side=side, entry=100., stop=95., target=110.)
    if side == "sell":
        params.update(stop=105., target=90.)
    params.update(changes)
    return PublishedSignal(**params)


def watch(bars, plan=None, **kwargs):
    plan = plan or signal()
    args = dict(as_of=BASE+timedelta(hours=2),
                quote_policy="buy_ask_sell_bid",
                max_bars=48)
    args.update(kwargs)
    return observe_quotes(
        plan, QuoteHistory(plan.venue, plan.symbol, "fabricated_for_tests",
                           tuple(bars)), **args)


class QuoteAuditTests(unittest.TestCase):
    def test_csv_fixture_and_reproducible_demo(self):
        loaded = load_quote_csv(SAMPLE)
        self.assertEqual(len(loaded.bars), 3)
        self.assertEqual(loaded.origin, "fabricated_for_tests")
        output = demo()
        self.assertEqual(output["price_level_observation"], "TARGET_LEVEL_TOUCHED")
        self.assertEqual(output["post_publication_bars_examined"], 2)
        self.assertIsNone(output["realized_PnL"])
        self.assertFalse(output["proven_market_outcome"])
        self.assertEqual(output["orders_sent"], 0)

    def test_skip_publication_candle(self):
        self.assertEqual(watch([bar(0, bo=100, bh=115, bl=94, bc=105)]).status,
                         "NO_POST_PUBLICATION_DATA")

    def test_long_ask_entry_then_bid_target(self):
        result = watch([bar(5), bar(10, bo=101, bh=111, bl=100, bc=110)])
        self.assertEqual(result.status, "TARGET_LEVEL_TOUCHED")

    def test_long_bid_touch_is_not_ask_entry(self):
        self.assertEqual(watch([bar(5, bo=101, bh=102, bl=99.9, bc=101)]).status,
                         "AWAITING_ENTRY_LEVEL")

    def test_long_ask_target_is_not_bid_target(self):
        result = watch([bar(5), bar(10, bo=101, bh=109.9, bl=100, bc=109.8)])
        self.assertEqual(result.status, "ENTRY_LEVEL_TOUCHED_AWAITING_OUTCOME")

    def test_short_bid_entry_then_ask_target(self):
        result = watch(
            [bar(5), bar(10, bo=99, bh=102, bl=89, bc=90, spread=.2)],
            plan=signal("sell")
        )
        self.assertEqual(result.status, "TARGET_LEVEL_TOUCHED")

    def test_short_ask_touch_does_not_mean_bid_entry(self):
        result = watch([bar(5, bo=98, bh=99.9, bl=97, bc=98.5)],
                       plan=signal("sell"))
        self.assertEqual(result.status, "AWAITING_ENTRY_LEVEL")

    def test_short_stop_uses_ask_quote(self):
        result = watch(
            [bar(5), bar(10, bo=100, bh=104.9, bl=99, bc=104.5)],
            plan=signal("sell")
        )
        self.assertEqual(result.status, "STOP_LEVEL_TOUCHED")

    def test_entry_bar_ambiguity(self):
        result = watch([bar(5, bo=101, bh=111, bl=99, bc=101)])
        self.assertEqual(result.status, "AMBIGUOUS_ENTRY_BAR")

    def test_stop_and_target_bar_ambiguity(self):
        result = watch([bar(5), bar(10, bo=101, bh=111, bl=94, bc=100)])
        self.assertEqual(result.status, "AMBIGUOUS_EXIT_BAR")

    def test_gap_beyond_level_is_not_a_profit(self):
        result = watch([bar(5), bar(10, bo=112, bh=113, bl=111, bc=112)])
        self.assertEqual(result.status, "GAP_EXIT_UNPRICED")

    def test_spread_limit_fails_closed(self):
        result = watch([bar(5, spread=1.0)], max_open_spread_pct=.2)
        self.assertEqual(result.status, "SPREAD_THRESHOLD_EXCEEDED")

    def test_unclosed_candles_not_used(self):
        result = watch([bar(5), bar(10, bo=101, bh=111, bl=100, bc=110)],
                       as_of=BASE+timedelta(minutes=12))
        self.assertEqual(result.status, "ENTRY_LEVEL_TOUCHED_AWAITING_OUTCOME")

    def test_wrong_venue_fails(self):
        plan = signal(venue="MFP-SANDBOX")
        with self.assertRaisesRegex(ValueError, "venue"):
            watch([bar(5)], plan=plan)

    def test_unknown_quote_basis_fails(self):
        with self.assertRaisesRegex(ValueError, "convention"):
            watch([bar(5)], quote_policy="midpoint")

    def test_expiry(self):
        result = watch([bar(5, bo=102, bh=104, bl=101, bc=102)], max_bars=1)
        self.assertEqual(result.status, "EXPIRED_NO_ENTRY")

    def test_ask_below_bid_rejected(self):
        q = bar(5)
        with self.assertRaises(ValueError):
            replace(q, ask_close=100)

    def test_timezone_naive_rejected(self):
        q = bar(5)
        with self.assertRaises(ValueError):
            replace(q, opened_at=datetime(2026, 6, 22, 12, 5))

    def test_mixed_csv_venue_rejected(self):
        source = SAMPLE.read_text(encoding="utf-8").splitlines()
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "bad.csv"
            source[-1] = source[-1].replace("SYNTHETIC_ONLY", "OTHER_VENUE", 1)
            p.write_text("\n".join(source)+"\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Mixed venue"):
                load_quote_csv(p)

    def test_unclosed_csv_bar_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "bad.csv"
            value = SAMPLE.read_text(encoding="utf-8").replace(",true,", ",false,", 1)
            p.write_text(value, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unclosed"):
                load_quote_csv(p)

    def test_bid_only_csv_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "bad.csv"
            value = SAMPLE.read_text(encoding="utf-8")
            # Removing the ask_open header demonstrates that we won't fabricate it.
            p.write_text(value.replace(",ask_open", ""), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly"):
                load_quote_csv(p)

    def test_duplicate_bars_rejected(self):
        q = bar(5)
        with self.assertRaisesRegex(ValueError, "overlap"):
            QuoteHistory("SYNTHETIC_ONLY", "TEST_XAUUSD",
                         "fabricated_for_tests", (q, q))

    def test_too_many_csv_rows_refused(self):
        with self.assertRaisesRegex(ValueError, "row limit"):
            load_quote_csv(SAMPLE, max_rows=2)

    def test_spread_threshold_invalid(self):
        with self.assertRaises(ValueError):
            watch([bar(5)], max_open_spread_pct=-1)


if __name__ == "__main__":
    unittest.main()
