"""Fibonacci geometry on confirmed SMC pivots — fictional cross-asset prices."""
from datetime import datetime, timedelta, timezone
from math import isclose
from unittest.mock import patch
import unittest

from smc_agent.engine import Candle, Pivot, analyze
from smc_agent.fibonacci import FibonacciObservation, observe_fibonacci


START = datetime(2026, 1, 5, tzinfo=timezone.utc)


def candles(side="buy", last=100, *, number=32):
    """Two obvious closed fractal anchors; otherwise largely flat candles."""
    items = []
    for i in range(number):
        t = START + timedelta(minutes=5*i)
        if i == 12:
            hi, lo, close = (101, 90, 100) if side == "buy" else (110, 99, 100)
        elif i == 23:
            hi, lo, close = (110, 99, 100) if side == "buy" else (101, 90, 100)
        else:
            hi, lo, close = 101, 99, 100
            if i == 29:
                close = last
                hi = max(hi, close)
                lo = min(lo, close)
        items.append(Candle(t, 100, hi, lo, close))
    return items


class FibonacciTests(unittest.TestCase):
    def test_buy_from_confirmed_low_to_high(self):
        obs = observe_fibonacci(candles("buy"), side="buy")
        self.assertIsNotNone(obs)
        self.assertEqual((obs.from_index, obs.to_index), (12, 23))
        self.assertEqual(obs.confirmed_at, 25)
        self.assertTrue(isclose(obs.start_price, 90))
        self.assertTrue(isclose(obs.end_price, 110))
        self.assertTrue(isclose(obs.price_50, 100))
        self.assertTrue(isclose(obs.price_618, 97.64))
        self.assertTrue(isclose(obs.price_705, 95.9))
        self.assertTrue(isclose(obs.price_786, 94.28))
        self.assertTrue(isclose(obs.zone_low, 94.28))
        self.assertTrue(isclose(obs.zone_high, 97.64))
        self.assertEqual(obs.status, "AGUARDANDO_RETRACAO_OTE")

    def test_sell_high_to_low_retracement(self):
        obs = observe_fibonacci(candles("sell"), side="sell")
        self.assertEqual((obs.from_index, obs.to_index), (12, 23))
        self.assertTrue(isclose(obs.price_50, 100))
        self.assertTrue(isclose(obs.price_618, 102.36))
        self.assertTrue(isclose(obs.price_705, 104.10))
        self.assertTrue(isclose(obs.price_786, 105.72))
        self.assertEqual(obs.status, "AGUARDANDO_RETRACAO_OTE")

    def test_unconfirmed_high_is_not_fibonacci_endpoint(self):
        self.assertIsNone(observe_fibonacci(candles("buy",number=25),side="buy"))
        self.assertEqual(observe_fibonacci(candles("buy",number=26),side="buy").confirmed_at,25)

    def test_recent_ote_touch_and_ob_confluence(self):
        obs = observe_fibonacci(candles("buy",last=96),side="buy")
        self.assertEqual(obs.status,"RETESTE_RECENTE_OTE")
        self.assertTrue(obs.recent_ote_retest)
        self.assertTrue(obs.ob_overlaps_ote(95,97))
        self.assertFalse(obs.ob_overlaps_ote(99,101))

    def test_price_closes_inside_ote_zone(self):
        items=candles("buy",last=100)
        last=items[-1]
        items[-1]=Candle(last.time,100,101,95,96)
        obs=observe_fibonacci(items,side="buy")
        self.assertTrue(obs.in_ote_zone)
        self.assertEqual(obs.status,"EM_ZONA_OTE")

    def test_swing_invalidation_for_long_and_short(self):
        for side, last_close in (("buy",80),("sell",120)):
            items=candles(side)
            prev=items[-1]
            items[-1]=Candle(prev.time,100,max(101,last_close),
                             min(99,last_close),last_close)
            obs=observe_fibonacci(items,side=side)
            self.assertEqual(obs.status,"SWING_INVALIDADO")
            self.assertFalse(obs.recent_ote_retest)
            self.assertFalse(obs.ob_overlaps_ote(obs.zone_low,obs.zone_high))

    def test_no_pivot_without_structure(self):
        items=[Candle(START+timedelta(minutes=i*5),
                      100+i,101+i,99+i,100+i) for i in range(50)]
        self.assertIsNone(observe_fibonacci(items,side="buy"))

    def test_works_on_small_fx_prices(self):
        # Same price geometry scaled down 10,000x, no fixed pip assumptions.
        fx=[Candle(x.time,x.open/10000,x.high/10000,
                   x.low/10000,x.close/10000) for x in candles("buy")]
        obs=observe_fibonacci(fx,side="buy")
        self.assertIsNotNone(obs)
        self.assertAlmostEqual(obs.price_618,.009764,places=8)

    def test_no_future_leak_in_earlier_prefix(self):
        items=candles("buy",last=96)
        prior=observe_fibonacci(items[:28],side="buy")
        full=observe_fibonacci(items,side="buy")
        self.assertEqual(prior.confirmed_at,full.confirmed_at)
        self.assertEqual(prior.from_index,full.from_index)
        self.assertEqual(prior.price_618,full.price_618)
        self.assertFalse(prior.recent_ote_retest)
        self.assertTrue(full.recent_ote_retest)

    def test_no_swings_with_price_body_too_small_relative_to_atr(self):
        self.assertIsNone(observe_fibonacci(
            candles("buy"),side="buy",min_impulse_atr=100))

    def test_invalid_configuration_rejected(self):
        for changes in ({"side":"hold"}, {"side":"buy","wing":0},
                        {"side":"buy","max_lookback":5},
                        {"side":"buy","min_impulse_atr":0},
                        {"side":"buy","retest_recent_bars":0}):
            with self.assertRaises(ValueError):
                observe_fibonacci(candles("buy"),**changes)

    def test_invalid_order_block_range_refused(self):
        obs=observe_fibonacci(candles("buy"),side="buy")
        with self.assertRaises(ValueError):
            obs.ob_overlaps_ote(101,99)

    def test_analyze_optional_fib_keeps_default_behavior(self):
        # Unit test optional filter without manufacturing an engine setup.
        from smc_agent.engine import macro_bias
        m=candles("buy")+candles("buy")  # chronological check would fail
        m=[Candle(START+timedelta(hours=i),100,101,99,100)
           for i in range(55)]
        e=[Candle(START+timedelta(minutes=i*5),100,101,99,100)
           for i in range(70)]
        with patch("smc_agent.engine.macro_bias",return_value=1), \
             patch("smc_agent.fibonacci.observe_fibonacci",return_value=None):
            self.assertIsNone(analyze(m,e,require_fibonacci=True))
        self.assertIsNone(analyze(m,e))  # remains valid legacy call


if __name__ == "__main__":
    unittest.main()
