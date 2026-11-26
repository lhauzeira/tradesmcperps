"""Unit tests with mocked MT5; NEVER connect an account."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from smc_agent.engine import Candle, OrderBlock, Signal
from smc_agent.monitor_local import (
    MonitorSnapshot, check_demo_account, capture, render_html, monitor
)


NOW = datetime(2026, 11, 25, 14, 2, tzinfo=timezone.utc)
SERVER = "XMGlobal-MT5 5"


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    def __init__(self, mode=0, server=SERVER):
        self.details = SimpleNamespace(trade_mode=mode, server=server)
        self.calls = []
    def account_info(self):
        self.calls.append("account_info")
        return self.details
    def symbol_info_tick(self, symbol):
        self.calls.append("symbol_info_tick")
        return SimpleNamespace(bid=4000.5, ask=4001.0,
                               time=int(NOW.timestamp()))
    def order_send(self, *a, **kw):
        raise AssertionError("Monitor must never send an order")


class FakeAdapter:
    def __init__(self, mt5=None):
        self.mt5 = mt5 or FakeMT5()
        self.symbol = "GOLD"
        self.calls = []
    def bars(self, timeframe, count):
        self.calls.append((timeframe, count))
        if timeframe == "M5":
            last_open = NOW.replace(minute=55, hour=13, second=0)
            step = timedelta(minutes=5)
        else:
            last_open = NOW.replace(minute=0, hour=13, second=0)
            step = timedelta(hours=1)
        return [Candle(last_open-(count-1-i)*step, 4000,
                       4001,3999,4000.5) for i in range(count)]


class MonitorTests(unittest.TestCase):
    def test_demo_account_allowed_without_exposing_id(self):
        check_demo_account(FakeMT5().account_info(), FakeMT5())

    def test_real_account_blocked_before_reading_bars(self):
        fake = FakeAdapter(FakeMT5(mode=2))
        with self.assertRaisesRegex(RuntimeError, "DEMO"):
            capture(fake, now=NOW)
        self.assertEqual(fake.calls, [])

    def test_wrong_server_blocked(self):
        fake = FakeAdapter(FakeMT5(server="AnotherBroker"))
        with self.assertRaisesRegex(RuntimeError, "Servidor"):
            capture(fake, now=NOW)
        self.assertEqual(fake.calls, [])

    def test_unknown_mode_constant_is_blocked(self):
        fake = FakeMT5()
        fake.ACCOUNT_TRADE_MODE_DEMO = None
        with self.assertRaisesRegex(RuntimeError, "não informa"):
            check_demo_account(fake.details, fake)

    def test_live_quote_and_closed_candles_without_signal(self):
        result = capture(FakeAdapter(), now=NOW)
        self.assertEqual(result.state, "AGUARDANDO SETUP SMC")
        self.assertEqual(result.quote_bid, 4000.5)
        self.assertEqual(result.quote_ask, 4001.0)
        self.assertEqual(result.h1_bias, "NEUTRO")
        self.assertEqual(result.last_closed_m5_utc,
                         "2026-11-25T14:00:00+00:00")
        self.assertIsNone(result.record)
        self.assertTrue(result.connected_to_demo)

    def test_old_m5_candle_never_reemitted_as_active_signal(self):
        old = NOW+timedelta(minutes=25)
        with patch("smc_agent.monitor_local.analyze") as spy:
            result = capture(FakeAdapter(), now=old)
        self.assertEqual(result.state, "DADOS ANTIGOS — SEM SINAL ATIVO")
        self.assertIsNone(result.record)
        spy.assert_not_called()

    def test_mock_smc_signal_is_labeled_not_operable(self):
        ob = OrderBlock("buy", 3998, 4000, 15, 20)
        signal = Signal("buy", 4000, 3998, 4005, 2.5,
                        ob, "BOS + OB experimental")
        with patch("smc_agent.monitor_local.analyze", return_value=signal):
            report = capture(FakeAdapter(), now=NOW)
        self.assertEqual(report.state, "SINAL DE PESQUISA — NÃO OPERAR")
        self.assertEqual(report.record.symbol, "GOLD")
        self.assertEqual(report.record.timeframe, "M5")
        self.assertEqual(report.record.candle_closed_at.isoformat(),
                         "2026-11-25T14:00:00+00:00")
        self.assertEqual(report.record.rr, 2.5)
        self.assertIn("NÃO OPERAR", render_html(report))

    def test_html_escapes_signal_explanation(self):
        ob = OrderBlock("buy", 3998, 4000, 15, 20)
        signal = Signal("buy", 4000, 3998, 4005, 2.5,
                        ob, "<script>alert('bad')</script>")
        with patch("smc_agent.monitor_local.analyze", return_value=signal):
            report = capture(FakeAdapter(), now=NOW)
        rendered = render_html(report)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_local_dashboard_has_no_remote_content(self):
        report = capture(FakeAdapter(), now=NOW)
        output = render_html(report)
        self.assertIn("meta http-equiv=\"refresh\"", output)
        self.assertNotIn("http://", output)
        self.assertNotIn("https://", output)
        self.assertIn("Ordens enviadas:", output)

    def test_bad_clock_timestamp_refused(self):
        with self.assertRaises(ValueError):
            capture(FakeAdapter(), now=datetime(2026, 11, 25, 14))

    def test_monitor_rejects_unsupported_symbols_and_fast_loop(self):
        with self.assertRaisesRegex(ValueError, "GOLD"):
            monitor(symbol="XAUUSD", once=True)
        with self.assertRaisesRegex(ValueError, "Intervalo"):
            monitor(interval=1, once=True)

    def test_signal_is_deduplicated_after_program_restart(self):
        from smc_agent import adapters
        from smc_agent.alerts import SignalRecord
        fake = FakeAdapter()
        class LocalMT5Adapter:
            def __init__(self, symbol):
                self.symbol = symbol
                self.mt5 = fake.mt5
            def connect(self):
                return fake.mt5.account_info()
            def close(self):
                pass
        signal = SignalRecord(
            event_id="synthetic-once-1", symbol="GOLD", timeframe="M5",
            candle_closed_at=NOW-timedelta(minutes=2),
            side="buy", entry=4000, stop=3998, target=4005,
            rr=2.5, reason="BOS + OB apenas teste",
            source="test-fixture",
        )
        snap = MonitorSnapshot(
            generated_utc=NOW.isoformat(), symbol="GOLD", server=SERVER,
            connected_to_demo=True, state="SINAL DE PESQUISA — NÃO OPERAR",
            last_closed_m5_utc=(NOW-timedelta(minutes=2)).isoformat(),
            record=signal
        )
        with tempfile.TemporaryDirectory() as root:
            with patch.object(adapters, "MT5Adapter", LocalMT5Adapter), \
                 patch("smc_agent.monitor_local.capture", return_value=snap), \
                 patch("smc_agent.monitor_local.webbrowser.open"):
                monitor(once=True, folder=Path(root))
                monitor(once=True, folder=Path(root))
            data = Path(root) / "monitoramento_privado"
            events = (data/"sinais.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(events), 1)
            self.assertIn("synthetic-once-1", events[0])
            self.assertTrue((data/"sinais.sqlite3").exists())
            self.assertNotIn("login", events[0])

    def test_atomic_local_file_and_synthetic_journal(self):
        # Test only local file IO with a fully mocked adapter, no MT5 package.
        from smc_agent import adapters
        fake = FakeAdapter()
        class LocalMT5Adapter:
            def __init__(self, symbol): self.symbol = symbol; self.mt5 = fake.mt5
            def connect(self): return fake.mt5.account_info()
            def bars(self, timeframe, count): return fake.bars(timeframe, count)
            def close(self): pass
        with tempfile.TemporaryDirectory() as root:
            with patch.object(adapters, "MT5Adapter", LocalMT5Adapter), \
                 patch("smc_agent.monitor_local.webbrowser.open") as open_tab, \
                 patch("smc_agent.monitor_local.datetime") as clock:
                clock.now.return_value = NOW
                monitor(once=True, folder=Path(root))
            self.assertTrue((Path(root) / "MONITOR_LOCAL_DEMO.html").exists())
            self.assertTrue((Path(root) / "monitoramento_privado" /
                             "analises_m5.jsonl").exists())
            open_tab.assert_called_once()


if __name__ == "__main__":
    unittest.main()
