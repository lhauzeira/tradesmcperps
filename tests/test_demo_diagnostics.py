"""Sanitized live terminal inventory tests with a FAKE XM DEMO MT5."""
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from smc_agent.demo_diagnostics import audit_demo_instruments, print_sanitized_report


class FakeXM:
    ACCOUNT_TRADE_MODE_DEMO=0
    SYMBOL_TRADE_MODE_FULL=4

    def __init__(self):
        self.calls=[]
        self.account=SimpleNamespace(
            trade_mode=0,server="XMGlobal-MT5 5",currency="USD",
            login=9999999,password="DO_NOT_PRINT",
            balance=123456.0,equity=222222.0
        )
        self.info=SimpleNamespace(
            digits=2,point=.01,trade_tick_size=.01,
            trade_tick_value_loss=1.5,volume_min=.01,
            volume_max=50.0,volume_step=.01,
            trade_stops_level=50,trade_mode=4
        )
    def account_info(self):
        self.calls.append("account_info")
        return self.account
    def symbol_select(self,symbol,show):
        self.calls.append(("symbol_select",symbol))
        return symbol!="UNKNOWN"
    def symbol_info(self,symbol):
        self.calls.append(("symbol_info",symbol))
        return self.info
    def symbol_info_tick(self,symbol):
        self.calls.append(("symbol_info_tick",symbol))
        return SimpleNamespace(bid=100.01,ask=100.02)
    def order_send(self,*args,**kwargs):
        raise AssertionError("No order send permitted")


class SanitizedDemoContractTests(unittest.TestCase):
    def test_three_assets_have_independent_read_only_entries(self):
        xm=FakeXM()
        report=audit_demo_instruments(xm,("GOLD","US100Cash","US500Cash"))
        self.assertEqual(len(report["instruments"]),3)
        self.assertEqual(report["currency"],"USD")
        self.assertEqual(report["orders_sent"],0)
        self.assertEqual(report["instruments"][0]["tick_value_loss"],"1.5")
        self.assertFalse(report["instruments"][0]["holiday_session_verified"])
        self.assertFalse(report["instruments"][0]["orders_enabled"])
        self.assertEqual(xm.calls.count("account_info"),1)
        self.assertFalse(any(v=="order_send" for v in xm.calls))

    def test_account_identity_and_balance_never_in_returned_report(self):
        import json
        xm=FakeXM()
        data=audit_demo_instruments(xm,("GOLD",))
        text=json.dumps(data)
        self.assertNotIn("9999999",text)
        self.assertNotIn("123456",text)
        self.assertNotIn("222222",text)
        self.assertNotIn("DO_NOT_PRINT",text)
        self.assertNotIn("login",text)
        self.assertNotIn("password",text)
        self.assertNotIn("equity",text)

    def test_real_account_refused_without_symbol_reads(self):
        xm=FakeXM()
        xm.account.trade_mode=2
        with self.assertRaisesRegex(RuntimeError,"somente conta DEMO"):
            audit_demo_instruments(xm,("GOLD",))
        self.assertEqual(xm.calls,["account_info"])

    def test_wrong_server_refused_without_symbol_reads(self):
        xm=FakeXM()
        xm.account.server="Other-Broker"
        with self.assertRaisesRegex(RuntimeError,"Servidor diferente"):
            audit_demo_instruments(xm,("GOLD",))
        self.assertEqual(xm.calls,["account_info"])

    def test_unavailable_symbol_does_not_stop_good_symbols(self):
        xm=FakeXM()
        report=audit_demo_instruments(xm,("GOLD","UNKNOWN","US500Cash"))
        self.assertEqual(report["instruments"][1],{
            "symbol":"UNKNOWN","state":"INDISPONIVEL"
        })
        self.assertEqual(report["instruments"][2]["symbol"],"US500Cash")

    def test_missing_tick_or_contract_data_is_unnamed_not_invented(self):
        xm=FakeXM()
        xm.info.trade_tick_value_loss=None
        report=audit_demo_instruments(xm,("GOLD",))
        self.assertIsNone(report["instruments"][0]["tick_value_loss"])
        xm=FakeXM()
        xm.symbol_info_tick=lambda _:None
        report=audit_demo_instruments(xm,("GOLD",))
        self.assertIsNone(report["instruments"][0]["bid"])
        self.assertIsNone(report["instruments"][0]["ask"])

    def test_invalid_symbol_list_and_missing_currency_rejected(self):
        xm=FakeXM()
        for symbols in ((),("GOLD","GOLD"),tuple("S"+str(i) for i in range(13))):
            with self.subTest(symbols=symbols):
                with self.assertRaises(ValueError):
                    audit_demo_instruments(xm,symbols)
        xm.account.currency=None
        with self.assertRaises(RuntimeError):
            audit_demo_instruments(xm,("GOLD",))

    def test_print_report_only_sanitized_fields(self):
        xm=FakeXM()
        report=audit_demo_instruments(xm,("GOLD",))
        output=StringIO()
        with patch("sys.stdout",output):
            print_sanitized_report(report)
        value=output.getvalue()
        self.assertIn("ZERO ORDENS",value)
        self.assertIn("volume_min",value)
        self.assertNotIn("9999999",value)
        self.assertNotIn("123456",value)

if __name__=="__main__":
    unittest.main()
