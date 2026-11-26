"""Market-independent scanner tests with a fake MT5 and no orders."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

from smc_agent.monitor_local import MonitorSnapshot
from smc_agent.multi_monitor import (
    MarketRow, read_symbol_list, observe_one, render_market_table, monitor_many,
)

BASE=datetime(2026,11,26,15,0,tzinfo=timezone.utc)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    def __init__(self):
        self.calls=[]
        self.shutdown_calls=0
        self.allowed={"GOLD":2,"EURUSD":5,"USDJPY":3,"BTCUSD":2}
    def initialize(self):
        self.calls.append("initialize")
        return True
    def account_info(self):
        self.calls.append("account_info")
        return SimpleNamespace(trade_mode=0,server="XMGlobal-MT5 5")
    def symbol_select(self,symbol,visible):
        self.calls.append(("symbol_select",symbol))
        return symbol in self.allowed
    def symbol_info(self,symbol):
        self.calls.append(("symbol_info",symbol))
        if symbol not in self.allowed:return None
        return SimpleNamespace(digits=self.allowed[symbol])
    def shutdown(self):
        self.shutdown_calls+=1
    def order_send(self,*args,**kwargs):
        raise AssertionError("No order allowed")


def snapshot(symbol="GOLD",digits=2):
    return MonitorSnapshot(
        generated_utc=BASE.isoformat(),symbol=symbol,server="XMGlobal-MT5 5",
        connected_to_demo=True,state="AGUARDANDO SETUP SMC",
        last_closed_m5_utc=BASE.isoformat(),quote_bid=1.09231,
        quote_ask=1.09242,last_m5_bid_close=1.09232,
        h1_bias="ALTA",price_digits=digits,clock_offset_label="UTC+02:00 (provisório)"
    )


class MultiMonitorTests(unittest.TestCase):
    def test_symbols_from_editable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"ATIVOS_DEMO.txt"
            path.write_text("# commented\nGOLD\nEURUSD\n# BTCUSD\n",encoding="utf-8")
            self.assertEqual(read_symbol_list(path),("GOLD","EURUSD"))
            path.write_text("GOLD\nGOLD\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"duplicado"):
                read_symbol_list(path)

    def test_invalid_symbol_and_too_many_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"ATIVOS_DEMO.txt"
            for txt in ("../../secret","http://broker","GOLD,EURUSD"):
                p.write_text(txt,encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"inválido"):
                    read_symbol_list(p)
            p.write_text("\n".join("ASSET"+str(i) for i in range(13)),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"1 a 12"):
                read_symbol_list(p)

    def test_empty_file_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"ATIVOS_DEMO.txt"
            p.write_text("# nothing\n",encoding="utf-8")
            with self.assertRaises(ValueError):
                read_symbol_list(p)

    def test_one_invalid_symbol_does_not_block_another(self):
        fake=FakeMT5()
        class Adapter:
            def __init__(self,symbol):self.symbol=symbol
        from smc_agent import adapters
        with patch.object(adapters,"MT5Adapter",Adapter), \
             patch("smc_agent.multi_monitor.capture",
                   side_effect=lambda a:snapshot(a.symbol,fake.allowed.get(a.symbol,2))):
            euro=observe_one(fake,"EURUSD")
            bad=observe_one(fake,"UNKNOWN_X")
            gold=observe_one(fake,"GOLD")
        self.assertIsNotNone(euro.snapshot)
        self.assertEqual(euro.snapshot.price_digits,5)
        self.assertIsNone(bad.snapshot)
        self.assertIsNotNone(gold.snapshot)

    def test_multi_panel_price_precision_and_local_only(self):
        html=render_market_table((
            MarketRow("GOLD",snapshot("GOLD",2),None),
            MarketRow("EURUSD",snapshot("EURUSD",5),None),
            MarketRow("GBPUSD",None,"Ativo não encontrado"),
        ),BASE.isoformat())
        self.assertIn("GOLD",html)
        self.assertIn("EURUSD",html)
        self.assertIn("1.09231",html)
        self.assertIn("1.09",html)
        self.assertIn("Ativo não encontrado",html)
        self.assertNotIn("https://",html)
        self.assertNotIn("http://",html)
        self.assertIn("Ordens enviadas: 0",html)

    def test_multi_safe_html_escaping(self):
        html=render_market_table((
            MarketRow("GOLD",None,"<script>alert(1)</script>"),
        ),BASE.isoformat())
        self.assertNotIn("<script>",html)
        self.assertIn("&lt;script&gt;",html)

    def test_real_account_blocks_all_symbol_reads(self):
        from smc_agent import adapters
        mt5=FakeMT5()
        mt5.account_info=lambda: SimpleNamespace(trade_mode=2,server="XMGlobal-MT5 5")
        class Adapter:
            def __init__(self,symbol):self.symbol=symbol;self.mt5=mt5
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"ATIVOS_DEMO.txt").write_text("GOLD\nEURUSD\n",encoding="utf-8")
            with patch.object(adapters,"MT5Adapter",Adapter), \
                 patch("smc_agent.multi_monitor.webbrowser.open"), \
                 patch("smc_agent.multi_monitor.observe_one") as observer:
                monitor_many(root=root,once=True)
                observer.assert_not_called()
            self.assertTrue(mt5.shutdown_calls>0)
            page=(root/"PAINEL_MULTI_DEMO.html").read_text(encoding="utf-8")
            self.assertIn("MONITOR PAUSADO",page)

    def test_scans_once_and_saves_each_symbol_separately(self):
        from smc_agent import adapters
        mt5=FakeMT5()
        class Adapter:
            def __init__(self,symbol):self.symbol=symbol;self.mt5=mt5
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"ATIVOS_DEMO.txt").write_text("GOLD\nEURUSD\n",encoding="utf-8")
            with patch.object(adapters,"MT5Adapter",Adapter), \
                 patch("smc_agent.multi_monitor.observe_one",
                     side_effect=lambda unused,symbol:
                         MarketRow(symbol,snapshot(symbol,mt5.allowed[symbol]),None)), \
                 patch("smc_agent.multi_monitor.webbrowser.open"):
                monitor_many(root=root,once=True)
            page=(root/"PAINEL_MULTI_DEMO.html").read_text(encoding="utf-8")
            self.assertIn("GOLD",page)
            self.assertIn("EURUSD",page)
            self.assertTrue((root/"monitoramento_privado"/"analises_multi.jsonl").exists())
            data=(root/"monitoramento_privado"/"analises_multi.jsonl").read_text(encoding="utf-8")
            self.assertEqual(len(data.strip().splitlines()),2)
            self.assertEqual(mt5.shutdown_calls,1)


if __name__=="__main__":
    unittest.main()
