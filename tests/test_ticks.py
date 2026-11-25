from datetime import datetime, timedelta, timezone
import unittest

from smc_agent.ticks import aggregate_bidask_ticks
from smc_agent.quotes import observe_quotes
from smc_agent.lifecycle import PublishedSignal
from smc_agent.adapters import MT5Adapter

BASE = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def tick(minute, seconds, bid, ask):
    at = BASE + timedelta(minutes=minute, seconds=seconds)
    return {"time_msc": int(at.timestamp()*1000), "bid": bid, "ask": ask}


def aggregate(data, cutoff=20, **overrides):
    kwargs = dict(venue="TEST_BROKER:SIMULATED", symbol="TEST_XAUUSD",
                  source="synthetic_tick_fixture", timeframe_seconds=300,
                  as_of=BASE+timedelta(minutes=cutoff))
    kwargs.update(overrides)
    return aggregate_bidask_ticks(data, **kwargs)


def raw():
    return [
        tick(0, 5, 100., 100.2),
        tick(4, 50, 101., 101.2),
        tick(5, 0, 99., 99.2),
        tick(9, 40, 101., 101.2),
        tick(10, 0, 100., 100.2),
        tick(14, 40, 110., 110.2),
    ]


class TickAggregationTests(unittest.TestCase):
    def test_bidask_bars_come_from_real_tick_values_not_spread_guess(self):
        history = aggregate(raw())
        self.assertEqual(len(history.bars), 3)
        self.assertEqual(history.bars[1].bid_low, 99.)
        self.assertEqual(history.bars[1].ask_low, 99.2)
        self.assertEqual(history.bars[2].bid_high, 110.)
        self.assertEqual(history.bars[2].ask_high, 110.2)
        self.assertEqual(history.origin, "synthetic_tick_fixture")

    def test_quote_observer_uses_reconstructed_quote_bars(self):
        history = aggregate(raw())
        plan = PublishedSignal(
            signal_id="ticktest-1", venue=history.venue, symbol=history.symbol,
            published_at=BASE+timedelta(minutes=2),
            side="buy", entry=100, stop=95, target=110
        )
        observation = observe_quotes(
            plan, history, as_of=BASE+timedelta(minutes=15),
            quote_policy="buy_ask_sell_bid")
        self.assertEqual(observation.status, "TARGET_LEVEL_TOUCHED")
        self.assertEqual(observation.bars_examined, 2)

    def test_incomplete_last_bar_excluded(self):
        # Supply only ticks observed by the cutoff; future ticks are rejected.
        history = aggregate(raw()[:5], cutoff=12)
        self.assertEqual(len(history.bars), 2)
        self.assertEqual(history.bars[-1].closed_at, BASE+timedelta(minutes=10))

    def test_no_closed_bar_fails(self):
        with self.assertRaisesRegex(ValueError, "No fully closed"):
            aggregate(raw()[:1], cutoff=2)

    def test_no_ticks_fails(self):
        with self.assertRaisesRegex(ValueError, "No fully closed"):
            aggregate([])

    def test_future_tick_fails(self):
        with self.assertRaisesRegex(ValueError, "Future tick"):
            aggregate(raw(), cutoff=6)

    def test_crossed_spread_fails(self):
        with self.assertRaisesRegex(ValueError, "crossed"):
            aggregate([tick(0, 5, 100, 99)])

    def test_zero_quote_fails(self):
        with self.assertRaisesRegex(ValueError, "crossed"):
            aggregate([tick(0, 5, 0, 1)])

    def test_out_of_order_ticks_fail(self):
        with self.assertRaisesRegex(ValueError, "not sorted"):
            aggregate([tick(4, 0, 100, 100.2), tick(1, 0, 99, 99.2)])

    def test_empty_provenance_fails(self):
        with self.assertRaisesRegex(ValueError, "provenance"):
            aggregate(raw(), venue="")

    def test_maximum_tick_count_fails(self):
        with self.assertRaisesRegex(ValueError, "maximum"):
            aggregate(raw(), max_ticks=2)

    def test_timestamp_needs_integer_epoch_ms(self):
        invalid = tick(0, 0, 100, 100.2)
        invalid["time_msc"] = "2026-06-22"
        with self.assertRaisesRegex(ValueError, "time_msc"):
            aggregate([invalid])

    def test_bucket_edges_align_to_utc(self):
        history = aggregate(raw())
        self.assertEqual(history.bars[0].opened_at, BASE)
        self.assertEqual(history.bars[0].closed_at, BASE+timedelta(minutes=5))
        self.assertEqual(history.bars[1].opened_at, BASE+timedelta(minutes=5))

    def test_time_without_zone_rejected(self):
        with self.assertRaises(ValueError):
            aggregate(raw(), as_of=datetime(2026, 6, 22, 13))

    def test_unsupported_interval_rejected(self):
        with self.assertRaisesRegex(ValueError, "interval"):
            aggregate(raw(), timeframe_seconds=173)


class FakeMT5:
    COPY_TICKS_INFO = 999

    def __init__(self):
        self.calls = []
        self.returned = raw()

    def copy_ticks_range(self, symbol, start, end, flag):
        self.calls.append((symbol, start, end, flag))
        return self.returned

    def order_send(self, *args, **kwargs):
        raise AssertionError("No trade execution should occur in read-only tests")


class MT5ReadOnlyTests(unittest.TestCase):
    def create_adapter(self):
        obj = object.__new__(MT5Adapter)
        obj.mt5 = FakeMT5()
        obj.symbol = "TEST_XAUUSD"
        return obj

    def test_ticks_returned_without_order_execution(self):
        adapter = self.create_adapter()
        history = adapter.quote_history(
            BASE, BASE+timedelta(minutes=15),
            timeframe_seconds=300,
            as_of=BASE+timedelta(minutes=20),
            venue="TEST_BROKER:SIMULATED"
        )
        self.assertEqual(len(history.bars), 3)
        self.assertEqual(len(adapter.mt5.calls), 1)
        self.assertEqual(adapter.mt5.calls[0][3], FakeMT5.COPY_TICKS_INFO)
        self.assertIn("UNVERIFIED_COVERAGE", history.origin)

    def test_reject_unverified_venue(self):
        adapter = self.create_adapter()
        with self.assertRaisesRegex(ValueError, "venue"):
            adapter.quote_history(
                BASE, BASE+timedelta(minutes=15),
                timeframe_seconds=300,
                as_of=BASE+timedelta(minutes=20),
                venue="MT5-UNVERIFIED"
            )
        self.assertEqual(adapter.mt5.calls, [])

    def test_reject_future_range_without_call(self):
        adapter = self.create_adapter()
        with self.assertRaisesRegex(ValueError, "time range"):
            adapter.quote_history(
                BASE, BASE+timedelta(minutes=30),
                timeframe_seconds=300,
                as_of=BASE+timedelta(minutes=20),
                venue="TEST_BROKER:SIMULATED"
            )
        self.assertEqual(adapter.mt5.calls, [])


if __name__ == "__main__":
    unittest.main()
