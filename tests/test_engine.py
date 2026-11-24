import unittest
from datetime import datetime, timezone, timedelta
from smc_agent.engine import Candle, atr_at, confirmed_pivots, order_blocks, analyze
from smc_agent.risk import RiskRules, allowed_loss, authorize_minimum_lot
from smc_agent.demo import report

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)


def make(values):
    bars = []
    for i, v in enumerate(values):
        o = values[i-1] if i else v
        bars.append(Candle(BASE+timedelta(minutes=5*i), o, max(v, o)+.1, min(v, o)-.1, v))
    return bars


class EngineTests(unittest.TestCase):
    def test_bad_ohlc(self):
        with self.assertRaises(ValueError):
            Candle(BASE, 10, 9, 8, 10)

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            Candle(datetime(2026,1,1), 10, 11, 9, 10)

    def test_fractals_only_after_confirmation(self):
        b = [Candle(BASE + timedelta(minutes=5*i), v, v+.1, v-.1, v)
             for i, v in enumerate([10, 11, 12, 16, 12, 11, 10, 11, 12])]
        self.assertFalse(any(p.index == 3 for p in confirmed_pivots(b, available_at=4)))
        self.assertTrue(any(p.index == 3 and p.confirmed_at == 5
                            for p in confirmed_pivots(b, available_at=5)))

    def test_atr_not_affected_by_future(self):
        b = make([100+i*.05 for i in range(30)])
        a = atr_at(b, 20)
        self.assertEqual(a, atr_at(b + make([999]), 20))

    def test_risk_guard(self):
        rules = RiskRules(risk_percent=1)
        self.assertAlmostEqual(allowed_loss(100, rules), .85)
        self.assertTrue(authorize_minimum_lot(100, .50, rules))
        self.assertFalse(authorize_minimum_lot(100, 1.00, rules))
        self.assertFalse(authorize_minimum_lot(100, 0, rules))

    def test_no_signal_without_structure(self):
        b = make([100+i*.02 for i in range(80)])
        self.assertIsNone(analyze(b, b))
        self.assertEqual(order_blocks(b), [])

    def test_offline_demo_has_no_orders(self):
        result = report()
        self.assertEqual(result["orders_sent"], 0)
        self.assertFalse(result["uses_real_market_data"])
        self.assertFalse(result["automated_execution"])


if __name__ == "__main__":
    unittest.main()
