"""Offline test of privacy-safe MT5 clock discrepancy diagnosis."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from smc_agent.clock_diagnostic import read_clock


NOW = datetime(2026, 11, 26, 15, 0, 20, tzinfo=timezone.utc)
SERVER = "XMGlobal-MT5 5"


class FakeClockMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 60

    def __init__(self, *, offset_seconds=0, demo=True, server=SERVER,
                 m5_age_seconds=20, tick_available=True):
        self.offset = offset_seconds
        self.demo = demo
        self.server = server
        self.age = m5_age_seconds
        self.tick_available = tick_available
        self.calls = []

    def account_info(self):
        self.calls.append("account_info")
        return SimpleNamespace(trade_mode=0 if self.demo else 2,
                               server=self.server, login=999999,
                               balance=123456.78)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.calls.append(f"rates:{timeframe}")
        if timeframe == self.TIMEFRAME_M5:
            end = int(NOW.timestamp()) + self.offset - self.age
            epoch = end - 300
        else:
            epoch = int(NOW.timestamp()) + self.offset - 3600
        return [{"time":epoch-300}, {"time":epoch}]

    def symbol_info_tick(self, symbol):
        self.calls.append("symbol_info_tick")
        if not self.tick_available:
            return None
        return SimpleNamespace(time=int(NOW.timestamp()) + self.offset - 5,
                               bid=4000, ask=4000.5, login=987654)


class ClockDiagnosticTests(unittest.TestCase):
    def test_coherent_demo_clock(self):
        mt5 = FakeClockMT5()
        d = read_clock(mt5, symbol="GOLD", now=NOW)
        self.assertEqual(d.difference_m5_end_minus_system_seconds, -20)
        self.assertEqual(d.difference_tick_minus_system_seconds, -5)
        self.assertIn("SEM ANOMALIA", d.status)
        self.assertEqual(mt5.calls[0], "account_info")
        self.assertEqual(mt5.calls[-1], "symbol_info_tick")

    def test_future_broker_like_offset_is_diagnosed_not_adjusted(self):
        mt5 = FakeClockMT5(offset_seconds=10800)
        d = read_clock(mt5, symbol="GOLD", now=NOW)
        self.assertIn("M5 NO FUTURO", d.status)
        self.assertEqual(d.difference_m5_end_minus_system_seconds, 10780)
        self.assertEqual(d.difference_tick_minus_system_seconds, 10795)
        report = d.report()
        self.assertIn("+3.00 h", report)
        self.assertIn("NÃO GERAR SINAIS", report)
        self.assertIn("interpretado como UTC", report)
        self.assertNotIn("999999", report)
        self.assertNotIn("987654", report)
        self.assertNotIn("123456", report)

    def test_stale_data_without_offset_stays_blocked(self):
        d = read_clock(FakeClockMT5(m5_age_seconds=3600),
                       symbol="GOLD", now=NOW)
        self.assertIn("M5 ANTIGO", d.status)

    def test_future_tick_is_reported_even_if_m5_is_near_now(self):
        mt5 = FakeClockMT5()
        original_tick = mt5.symbol_info_tick

        def future_tick(symbol):
            out = original_tick(symbol)
            out.time += 7200
            return out

        mt5.symbol_info_tick = future_tick
        d = read_clock(mt5, symbol="GOLD", now=NOW)
        self.assertIn("TICK NO FUTURO", d.status)

    def test_unavailable_tick_is_not_fabricated(self):
        d = read_clock(FakeClockMT5(tick_available=False),
                       symbol="GOLD", now=NOW)
        self.assertIsNone(d.difference_tick_minus_system_seconds)
        self.assertIn("INDISPONÍVEL", d.report())

    def test_real_account_denied_before_market_fetch(self):
        mt5 = FakeClockMT5(demo=False)
        with self.assertRaisesRegex(RuntimeError, "DEMO"):
            read_clock(mt5, symbol="GOLD", now=NOW)
        self.assertEqual(mt5.calls, ["account_info"])

    def test_unknown_server_denied_before_market_fetch(self):
        mt5 = FakeClockMT5(server="AnotherBroker")
        with self.assertRaisesRegex(RuntimeError, "Servidor diferente"):
            read_clock(mt5, symbol="GOLD", now=NOW)
        self.assertEqual(mt5.calls, ["account_info"])

    def test_refuse_other_instruments(self):
        mt5 = FakeClockMT5()
        with self.assertRaises(ValueError):
            read_clock(mt5, symbol="EURUSD", now=NOW)
        self.assertEqual(mt5.calls, [])

    def test_clock_must_be_aware(self):
        mt5 = FakeClockMT5()
        with self.assertRaises(ValueError):
            read_clock(mt5, symbol="GOLD", now=datetime(2026, 11, 26))
        self.assertEqual(mt5.calls, [])

    def test_missing_m5_bars(self):
        mt5 = FakeClockMT5()
        orig = mt5.copy_rates_from_pos
        def broken(symbol, timeframe, start, count):
            if timeframe == mt5.TIMEFRAME_M5:
                return None
            return orig(symbol, timeframe, start, count)
        mt5.copy_rates_from_pos = broken
        with self.assertRaisesRegex(RuntimeError, "M5"):
            read_clock(mt5, symbol="GOLD", now=NOW)

    def test_missing_h1_bars(self):
        mt5 = FakeClockMT5()
        orig = mt5.copy_rates_from_pos
        def broken(symbol, timeframe, start, count):
            if timeframe == mt5.TIMEFRAME_H1:
                return []
            return orig(symbol, timeframe, start, count)
        mt5.copy_rates_from_pos = broken
        with self.assertRaisesRegex(RuntimeError, "H1"):
            read_clock(mt5, symbol="GOLD", now=NOW)

    def test_no_account_identifier_present_in_report(self):
        d = read_clock(FakeClockMT5(), symbol="GOLD", now=NOW)
        report = d.report()
        self.assertNotIn("login=", report)
        self.assertNotIn("ACCOUNT_TRADE_MODE", report)
        self.assertNotIn("balance=", report)


if __name__ == "__main__":
    unittest.main()
