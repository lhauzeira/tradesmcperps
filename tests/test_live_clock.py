"""The LIVE-only timestamp offset must be independently observed each scan.

All values in these tests are fabricated except one timestamp pattern
taken from the user's diagnostic screenshot, never from an account login.
"""
from datetime import datetime, timedelta, timezone
import unittest

from smc_agent.live_clock import reconcile_live_clock


UTC = timezone.utc
NOW = datetime(2026, 11, 26, 15, 42, 8, 977324, tzinfo=UTC)


def inspect(*, offset=7200, when=NOW, tick_lag=1,
            m5_open=None, h1_open=None):
    raw_tick = when.timestamp() + offset - tick_lag
    if m5_open is None:
        m5_open = datetime(2026, 11, 26, 15, 35, tzinfo=UTC) + timedelta(seconds=offset)
    if h1_open is None:
        h1_open = datetime(2026, 11, 26, 14, 0, tzinfo=UTC) + timedelta(seconds=offset)
    return reconcile_live_clock(
        now=when, raw_tick_seconds=raw_tick,
        raw_m5_open=m5_open, raw_h1_open=h1_open
    )


class LiveXMTimeTests(unittest.TestCase):
    def test_user_diagnostic_sample_26_nov_plus_two_hours(self):
        result = reconcile_live_clock(
            now=NOW, raw_tick_seconds=int(datetime(
                2026, 11, 26, 17, 42, 8, tzinfo=UTC).timestamp()),
            raw_m5_open=datetime(2026, 11, 26, 17, 35, tzinfo=UTC),
            raw_h1_open=datetime(2026, 11, 26, 16, 0, tzinfo=UTC),
        )
        self.assertEqual(result.observed_offset_seconds, 7200)
        self.assertEqual(result.m5_closed_utc,
                         datetime(2026, 11, 26, 15, 40, tzinfo=UTC))
        self.assertEqual(result.h1_closed_utc,
                         datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
        self.assertAlmostEqual(result.m5_age_seconds, 128.98, places=1)
        self.assertIn("UTC+02:00", result.offset_label)
        self.assertIn("NOT_HISTORICALLY_VERIFIED", result.confidence)

    def test_utc_native_no_offset(self):
        x = inspect(offset=0)
        self.assertEqual(x.observed_offset_seconds, 0)
        self.assertEqual(x.m5_closed_utc.hour, 15)

    def test_summer_offset_only_if_tick_and_bars_both_agree(self):
        x = inspect(offset=10800)
        self.assertEqual(x.observed_offset_seconds, 10800)
        self.assertIn("UTC+03:00", x.offset_label)
        self.assertEqual(x.m5_closed_utc.hour, 15)

    def test_missing_tick_fails_closed(self):
        for bad in (None, 0, float("nan"), float("inf"), True, "7200"):
            with self.assertRaises(RuntimeError):
                inspect_tick(bad)

    def test_fractional_offset_not_silently_rounded(self):
        with self.assertRaisesRegex(RuntimeError, "divergentes"):
            inspect(offset=7200+1800)

    def test_tick_older_than_one_minute_refused(self):
        with self.assertRaisesRegex(RuntimeError, "tick GOLD antigo"):
            inspect(tick_lag=200)

    def test_tick_clock_future_more_than_ten_seconds_refused(self):
        with self.assertRaisesRegex(RuntimeError, "divergentes"):
            inspect(tick_lag=-30)

    def test_m5_future_after_correction_refused(self):
        future_m5 = datetime(2026, 11, 26, 15, 45, tzinfo=UTC) + timedelta(hours=2)
        with self.assertRaisesRegex(RuntimeError, "Candle M5"):
            inspect(m5_open=future_m5)

    def test_h1_future_after_correction_refused(self):
        future_h1 = datetime(2026, 11, 26, 16, 0, tzinfo=UTC) + timedelta(hours=2)
        with self.assertRaisesRegex(RuntimeError, "Candle H1"):
            inspect(h1_open=future_h1)

    def test_m5_stale_after_correction_refused(self):
        old = datetime(2026, 11, 26, 14, 45, tzinfo=UTC) + timedelta(hours=2)
        with self.assertRaisesRegex(RuntimeError, "Candle M5"):
            inspect(m5_open=old)

    def test_h1_stale_after_correction_refused(self):
        old_h1 = datetime(2026, 11, 26, 10, 0, tzinfo=UTC) + timedelta(hours=2)
        with self.assertRaisesRegex(RuntimeError, "Candle H1"):
            inspect(h1_open=old_h1)

    def test_m5_not_aligned_refused(self):
        bad = datetime(2026, 11, 26, 15, 36, tzinfo=UTC) + timedelta(hours=2)
        with self.assertRaisesRegex(RuntimeError, "Alinhamento"):
            inspect(m5_open=bad)

    def test_h1_not_aligned_refused(self):
        bad = datetime(2026, 11, 26, 14, 1, tzinfo=UTC) + timedelta(hours=2)
        with self.assertRaisesRegex(RuntimeError, "Alinhamento"):
            inspect(h1_open=bad)

    def test_naive_now_refused(self):
        with self.assertRaisesRegex(ValueError, "now"):
            inspect(when=NOW.replace(tzinfo=None))

    def test_naive_bar_refused(self):
        with self.assertRaisesRegex(ValueError, "raw_m5_open"):
            inspect(m5_open=datetime(2026, 11, 26, 17, 35))

    def test_timestamp_gap_between_tick_and_recent_closed_m5_refused(self):
        near_new_m5 = datetime(2026, 11, 26, 15, 40, tzinfo=UTC) + timedelta(hours=2)
        # Closed 15:45, but raw tick is at 15:42 -> impossible.
        with self.assertRaisesRegex(RuntimeError, "Candle M5"):
            inspect(m5_open=near_new_m5)

    def test_h1_close_inconsistent_with_tick_refused(self):
        future_h1 = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)+timedelta(hours=2)
        with self.assertRaisesRegex(RuntimeError, "Candle H1"):
            inspect(h1_open=future_h1)


def inspect_tick(value):
    return reconcile_live_clock(
        now=NOW, raw_tick_seconds=value,
        raw_m5_open=datetime(2026, 11, 26, 17, 35, tzinfo=UTC),
        raw_h1_open=datetime(2026, 11, 26, 16, 0, tzinfo=UTC),
    )


if __name__ == "__main__":
    unittest.main()
