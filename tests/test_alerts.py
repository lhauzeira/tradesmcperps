import unittest
from dataclasses import replace
from datetime import datetime, timezone, timedelta

from smc_agent.engine import Signal, OrderBlock
from smc_agent.alerts import AlertBuffer, from_engine, telegram_preview

STAMP = datetime(2026, 1, 5, 15, 5, tzinfo=timezone.utc)


def sample(side="buy", reason="BOS & <OB>"):
    ob = OrderBlock(side, 99., 101., 30, 33)
    if side == "buy":
        return Signal(side, 102., 100., 107., 2.5, ob, reason)
    return Signal(side, 98., 100., 93., 2.5, ob, reason)


def rec(side="buy", at=STAMP):
    return from_engine(sample(side), symbol="XAUUSD", timeframe="M5",
                       candle_closed_at=at)


class AlertTests(unittest.TestCase):
    def test_stable_identity_dedup(self):
        a, b = rec(), rec()
        self.assertEqual(a.event_id, b.event_id)
        buffer = AlertBuffer()
        self.assertTrue(buffer.enqueue(a))
        self.assertFalse(buffer.enqueue(b))

    def test_new_closed_bar_is_new_alert(self):
        a, b = rec(), rec(at=STAMP + timedelta(minutes=5))
        self.assertNotEqual(a.event_id, b.event_id)
        buffer = AlertBuffer()
        self.assertTrue(buffer.enqueue(a))
        self.assertTrue(buffer.enqueue(b))

    def test_timezone_normalization(self):
        shifted = STAMP.astimezone(timezone(timedelta(hours=-3)))
        self.assertEqual(rec().event_id, rec(at=shifted).event_id)
        self.assertEqual(rec(at=shifted).candle_closed_at, STAMP)

    def test_message_sanitization(self):
        message = telegram_preview(rec())
        self.assertIn("BOS &amp; &lt;OB&gt;", message)
        self.assertIn("SIMULACAO DE ALERTA", message)
        self.assertIn("sem ordem", message)

    def test_both_directions(self):
        self.assertIn("VENDA", telegram_preview(rec("sell")))
        self.assertIn("COMPRA", telegram_preview(rec("buy")))

    def test_invalid_time_rejected(self):
        with self.assertRaises(ValueError):
            rec(at=datetime(2026, 1, 5, 15, 5))

    def test_directional_stop_guard(self):
        with self.assertRaises(ValueError):
            replace(rec(), stop=104.)

    def test_bad_rr_guard(self):
        with self.assertRaises(ValueError):
            replace(rec(), rr=10.)

    def test_market_symbol_validation(self):
        with self.assertRaises(ValueError):
            from_engine(sample(), symbol="<script>", timeframe="M5", candle_closed_at=STAMP)

    def test_invalid_market_price(self):
        with self.assertRaises(ValueError):
            replace(rec(), entry=float("nan"))


if __name__ == "__main__":
    unittest.main()
