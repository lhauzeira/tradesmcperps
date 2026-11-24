import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from smc_agent.lifecycle import ObservedBar, PublishedSignal, observe
from smc_agent.import_legacy import flags_for_row, summarize_csv, REQUIRED_COLUMNS


BASE = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def sample_signal(**changes):
    default = dict(signal_id="example-1", venue="XM-MT5", symbol="XAUUSD",
                   published_at=BASE + timedelta(minutes=2),
                   side="buy", entry=100., stop=95., target=110.)
    default.update(changes)
    return PublishedSignal(**default)


def bar(open_minute, o, h, l, c):
    start = BASE + timedelta(minutes=open_minute)
    return ObservedBar(start, start+timedelta(minutes=5), o, h, l, c)


def audit(bars, **kwargs):
    defaults = dict(feed_venue="XM-MT5", feed_symbol="XAUUSD",
                    as_of=BASE+timedelta(hours=4))
    defaults.update(kwargs)
    return observe(sample_signal(), bars, **defaults)


class LifecycleTests(unittest.TestCase):
    def test_ignore_candle_partly_before_publication(self):
        first = bar(0, 100, 115, 94, 105)
        self.assertEqual(audit([first]).status, "NO_POST_PUBLICATION_DATA")

    def test_entry_then_target_on_later_candle(self):
        result = audit([
            bar(5, 101, 103, 99, 101),
            bar(10, 101, 111, 100, 110),
        ])
        self.assertEqual(result.status, "TARGET_LEVEL_TOUCHED")
        self.assertIsNotNone(result.entry_touch_at)

    def test_entry_then_stop_on_later_candle(self):
        result = audit([
            bar(5, 101, 103, 99, 101),
            bar(10, 101, 102, 94, 95),
        ])
        self.assertEqual(result.status, "STOP_LEVEL_TOUCHED")

    def test_entry_and_stop_in_same_candle_is_ambiguous(self):
        result = audit([bar(5, 101, 103, 94, 100)])
        self.assertEqual(result.status, "AMBIGUOUS_ENTRY_BAR")

    def test_entry_and_target_in_same_candle_is_ambiguous(self):
        result = audit([bar(5, 101, 111, 99, 110)])
        self.assertEqual(result.status, "AMBIGUOUS_ENTRY_BAR")

    def test_both_exit_levels_same_candle_are_ambiguous(self):
        result = audit([
            bar(5, 101, 103, 99, 101),
            bar(10, 101, 112, 94, 102),
        ])
        self.assertEqual(result.status, "AMBIGUOUS_EXIT_BAR")

    def test_gap_beyond_target_never_assumes_fill(self):
        result = audit([
            bar(5, 101, 103, 99, 101),
            bar(10, 112, 113, 111, 112),
        ])
        self.assertEqual(result.status, "GAP_EXIT_UNPRICED")

    def test_pending_and_expiry(self):
        bars = [bar(5, 102, 103, 101, 102), bar(10, 102, 104, 101, 103)]
        self.assertEqual(audit(bars, max_bars=3).status, "AWAITING_ENTRY_LEVEL")
        self.assertEqual(audit(bars, max_bars=2).status, "EXPIRED_NO_ENTRY")

    def test_entry_touch_without_resolution(self):
        bars = [bar(5, 101, 103, 99, 101), bar(10, 101, 104, 99, 103)]
        self.assertEqual(audit(bars, max_bars=3).status, "ENTRY_LEVEL_TOUCHED_AWAITING_OUTCOME")
        self.assertEqual(audit(bars, max_bars=2).status, "UNRESOLVED_AFTER_ENTRY")

    def test_unclosed_candle_excluded(self):
        bars = [bar(5, 101, 103, 99, 101), bar(10, 101, 111, 100, 110)]
        result = audit(bars, as_of=BASE+timedelta(minutes=12))
        self.assertEqual(result.status, "ENTRY_LEVEL_TOUCHED_AWAITING_OUTCOME")

    def test_cross_venue_rejected(self):
        with self.assertRaises(ValueError):
            audit([bar(5, 101, 103, 99, 101)], feed_venue="MyFundedPerps")

    def test_overlap_rejected(self):
        first = bar(5, 101, 103, 99, 101)
        overlapping = ObservedBar(
            BASE+timedelta(minutes=8), BASE+timedelta(minutes=13),
            101, 103, 99, 101)
        with self.assertRaises(ValueError):
            audit([first, overlapping])

    def test_bad_price_plan_rejected(self):
        with self.assertRaises(ValueError):
            sample_signal(stop=105)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            sample_signal(published_at=datetime(2026, 6, 22))

    def test_max_bars_validation(self):
        with self.assertRaises(ValueError):
            audit([], max_bars=0)

    def test_sell_branch_touches_target(self):
        sell = sample_signal(side="sell", entry=100, stop=105, target=90)
        result = observe(sell, [
            bar(5, 99, 101, 98, 99),
            bar(10, 98, 100, 89, 92),
        ], feed_venue="XM-MT5", feed_symbol="XAUUSD",
            as_of=BASE+timedelta(minutes=30))
        self.assertEqual(result.status, "TARGET_LEVEL_TOUCHED")


def example_row(**changes):
    row = {k: "" for k in REQUIRED_COLUMNS}
    row.update(dict(id="message000", date="22.06.2026 14:05:39 GMT-03:00",
                    category="ICC spot", symbol="XAUUSD", side="SELL",
                    entry_type="quoted_entry", entry="100", stop="105", target="90",
                    rr_calc="2", rr_label="2", duplicate_of_prior="False"))
    row.update(changes)
    return row


class ImportPreflightTests(unittest.TestCase):
    def test_timing_warning_and_no_win_claim(self):
        flags = flags_for_row(example_row(time_diff_hours="2.73"))
        self.assertIn("SCHEDULE_OR_TIMEZONE_REVIEW", flags)
        self.assertIn("VENUE_FEED_MAPPING_REQUIRED", flags)
        self.assertNotIn("INVALID_PRICE_ORDER", flags)

    def test_future_candle_flagged_without_fraud_claim(self):
        flags = flags_for_row(example_row(candle_used_future_minutes="160.9"))
        self.assertIn("CANDLE_TIMESTAMP_REVIEW", flags)

    def test_zone_and_duplicate_marked(self):
        flags = flags_for_row(example_row(entry_type="zone_only", entry="",
                                          stop="", target="",
                                          duplicate_of_prior="True"))
        self.assertIn("SETUP_WITHOUT_FIXED_ENTRY", flags)
        self.assertIn("REPEATED_PARAMETERS", flags)
        self.assertNotIn("MISSING_PRICE_LEVEL", flags)

    def test_risk_reward_label_mismatch(self):
        flags = flags_for_row(example_row(rr_label="3.2"))
        self.assertIn("RR_LABEL_MISMATCH", flags)

    def test_invalid_prices(self):
        flags = flags_for_row(example_row(side="BUY", stop="105", target="90"))
        self.assertIn("INVALID_PRICE_ORDER", flags)

    def test_summary_never_reports_win_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)/"audit.csv"
            with open(dest, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=sorted(REQUIRED_COLUMNS), delimiter=";")
                writer.writeheader()
                writer.writerow(example_row())
                writer.writerow(example_row(id="message001", duplicate_of_prior="True"))
            summary = summarize_csv(dest)
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["records_with_three_price_levels"], 2)
        self.assertEqual(summary["distinct_quoted_parameter_combinations"], 1)
        self.assertEqual(summary["quality_flags"]["REPEATED_PARAMETERS"], 1)
        self.assertFalse(summary["execution_or_trade_outcome_verified"])
        self.assertIsNone(summary["historical_win_rate"])


if __name__ == "__main__":
    unittest.main()
