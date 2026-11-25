import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
import unittest

from smc_agent.mt5_export import inspect_mt5_export, load_mt5_quote_export

HEADER = "<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>\n"
BODY = (
    "2026.06.22\t17:00:00.089\t100.00\t100.20\t\t\t102\n"
    "2026.06.22\t17:00:01.100\t99.90\t\t\t\t98\n"
    "2026.06.22\t17:00:02.100\t\t100.30\t\t\t100\n"
    "2026.06.22\t17:04:59.500\t101.00\t101.20\t\t\t102\n"
    "2026.06.22\t17:05:00.000\t101.10\t101.30\t\t\t102\n"
    "2026.06.22\t17:05:01.000\t\t\t\t\t96\n"
)


def source(tmp, raw=HEADER + BODY):
    p = Path(tmp) / "MT5_fixture.csv"
    p.write_text(raw, encoding="utf-8")
    return p


class MT5CSVTests(unittest.TestCase):
    def test_counts_and_timezone_left_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            q = inspect_mt5_export(source(folder))
        self.assertEqual(q.records, 6)
        self.assertEqual(q.complete_bid_ask, 3)
        self.assertEqual(q.bid_only, 1)
        self.assertEqual(q.ask_only, 1)
        self.assertEqual(q.neither, 1)
        self.assertEqual(q.source_timezone, "UNSPECIFIED_IN_EXPORT")

    def test_offset_is_mandatory(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "UTC offset"):
                load_mt5_quote_export(
                    source(folder), venue="TEST_BROKER", symbol="GOLD",
                    verified_utc_offset_minutes=None, timeframe_seconds=300,
                    as_of=datetime(2026, 6, 22, 14, 8, tzinfo=timezone.utc)
                )

    def test_reconstruction_of_only_complete_ticks(self):
        with tempfile.TemporaryDirectory() as folder:
            history = load_mt5_quote_export(
                source(folder), venue="TEST_BROKER", symbol="GOLD",
                verified_utc_offset_minutes=180, timeframe_seconds=300,
                as_of=datetime(2026, 6, 22, 14, 8, tzinfo=timezone.utc)
            )
        self.assertEqual(len(history.bars), 1)
        b = history.bars[0]
        self.assertEqual(b.opened_at, datetime(2026, 6, 22, 14, tzinfo=timezone.utc))
        self.assertEqual(b.bid_low, 100.0)  # 99.90 was Bid-only and was not guessed
        self.assertEqual(b.ask_high, 101.2)  # 100.30 was Ask-only
        self.assertEqual(history.symbol, "GOLD")
        self.assertIn("COVERAGE_REVIEW", history.origin)

    def test_complete_second_bar_when_cutoff_later(self):
        with tempfile.TemporaryDirectory() as folder:
            history = load_mt5_quote_export(
                source(folder), venue="TEST_BROKER", symbol="GOLD",
                verified_utc_offset_minutes=180, timeframe_seconds=300,
                as_of=datetime(2026, 6, 22, 14, 11, tzinfo=timezone.utc)
            )
        self.assertEqual(len(history.bars), 2)

    def test_invalid_offset_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                load_mt5_quote_export(
                    source(folder), venue="TEST_BROKER", symbol="GOLD",
                    verified_utc_offset_minutes=950, timeframe_seconds=300,
                    as_of=datetime(2026, 6, 22, 14, 11, tzinfo=timezone.utc)
                )

    def test_empty_price_tick_is_not_synthetic_quote(self):
        with tempfile.TemporaryDirectory() as folder:
            p = source(folder, HEADER + "2026.06.22\t17:05:00.000\t\t\t\t\t96\n")
            q = inspect_mt5_export(p)
            self.assertEqual(q.complete_bid_ask, 0)
            with self.assertRaisesRegex(ValueError, "No fully closed"):
                load_mt5_quote_export(
                    p, venue="TEST_BROKER", symbol="GOLD",
                    verified_utc_offset_minutes=180, timeframe_seconds=300,
                    as_of=datetime(2026, 6, 22, 14, 11, tzinfo=timezone.utc)
                )

    def test_repeated_timestamp_rejected(self):
        raw = HEADER + BODY.splitlines(keepends=True)[0]*2
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "repeated"):
                inspect_mt5_export(source(folder, raw))

    def test_crossed_quote_rejected(self):
        raw = HEADER + "2026.06.22\t17:00:00.089\t100.50\t100.20\t\t\t102\n"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "Ask below"):
                inspect_mt5_export(source(folder, raw))

    def test_bad_header_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "header"):
                inspect_mt5_export(source(folder, "DATE,TIME,BID,ASK\n"))

    def test_no_unverified_symbol_or_venue(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "venue"):
                load_mt5_quote_export(
                    source(folder), venue="", symbol="GOLD",
                    verified_utc_offset_minutes=180, timeframe_seconds=300,
                    as_of=datetime(2026, 6, 22, 14, 11, tzinfo=timezone.utc)
                )

    def test_gaps_counted_without_filling(self):
        raw = (HEADER +
            "2026.06.22\t17:00:00.089\t100.00\t100.20\t\t\t102\n" +
            "2026.06.22\t18:01:02.200\t101.00\t101.20\t\t\t102\n")
        with tempfile.TemporaryDirectory() as folder:
            quality = inspect_mt5_export(source(folder, raw))
        self.assertEqual(quality.gaps_over_300s, 1)
        self.assertGreater(quality.max_gap_seconds, 3600)

    def test_row_cap_honored(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "maximum"):
                inspect_mt5_export(source(folder), max_rows=2)


if __name__ == "__main__":
    unittest.main()
