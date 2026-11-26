"""Read-only SMC-to-XM DEMO min-lot preflight tests with fake prices."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from smc_agent.alerts import SignalRecord
from smc_agent.monitor_local import MonitorSnapshot
from smc_agent.demo_signal_probe import probe_research_signal
from smc_agent.multi_monitor import observe_one

NOW=datetime(2026,11,26,17,30,tzinfo=timezone.utc)


def signal(**kwargs):
    fields=dict(
        event_id="SMC-SYNTHETIC-1",symbol="GOLD",timeframe="M5",
        candle_closed_at=NOW-timedelta(minutes=1),
        side="buy",entry=100.2,stop=99.0,target=103.2,
        rr=2.5,reason="synthetic",source="fixture",
    )
    fields.update(kwargs)
    return SignalRecord(**fields)


def snapshot(**kwargs):
    fields=dict(
        generated_utc=(NOW-timedelta(seconds=1)).isoformat(),
        symbol="GOLD",server="XMGlobal-MT5 5",connected_to_demo=True,
        state="SINAL DE PESQUISA — NÃO OPERAR",
        last_closed_m5_utc=(NOW-timedelta(minutes=1)).isoformat(),
        last_closed_h1_utc=(NOW-timedelta(minutes=30)).isoformat(),
        quote_time_utc=(NOW-timedelta(seconds=2)).isoformat(),
        quote_bid=100.0,quote_ask=100.2,m5_atr_price=4.0,
        clock_offset_label="UTC+02:00 (observado agora, provisório)",
        h1_bias="ALTA",m5_bias="ALTA",
    )
    fields.update(kwargs)
    return MonitorSnapshot(**fields)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    SYMBOL_TRADE_MODE_FULL=4
    ORDER_TYPE_BUY=0
    ORDER_TYPE_SELL=1
    def __init__(self):
        self.calls=[]
        self.acc=SimpleNamespace(
            trade_mode=0,server="XMGlobal-MT5 5",currency="USD",
            equity=10000,margin_free=8000,
            trade_allowed=True,trade_expert=True
        )
        self.spec=SimpleNamespace(
            digits=2,trade_mode=4,volume_min=.01,volume_max=5,
            volume_step=.01,trade_tick_size=.01,point=.01,
            trade_stops_level=20
        )
    def account_info(self):
        self.calls.append("account_info")
        return self.acc
    def symbol_info(self,s):
        self.calls.append("symbol_info")
        return self.spec
    def symbol_select(self,s,enable):
        self.calls.append("symbol_select")
        return True
    def symbol_info_tick(self,s):
        self.calls.append("symbol_info_tick")
        return SimpleNamespace(bid=100.0,ask=100.2)
    def positions_get(self):
        self.calls.append("positions_get")
        return ()
    def orders_get(self):
        self.calls.append("orders_get")
        return ()
    def order_calc_profit(self,side,symbol,lots,entry,stop):
        self.calls.append("order_calc_profit")
        return (stop-entry)*lots*100 if side==0 else (entry-stop)*lots*100
    def order_calc_margin(self,side,symbol,lots,entry):
        self.calls.append("order_calc_margin")
        return lots*1000
    def order_send(self,*args,**kwargs):
        raise AssertionError("NO ORDER SEND ALLOWED")


class ReadOnlySignalProbeTests(unittest.TestCase):
    def test_fresh_signal_estimates_minimum_lot_loss_not_actual_order(self):
        mt5=FakeMT5()
        report=probe_research_signal(mt5,signal(),snapshot(),now=NOW)
        self.assertEqual(report.account_currency,"USD")
        self.assertAlmostEqual(
            float(report.theoretical_loss_account_currency),1.2
        )
        self.assertAlmostEqual(
            float(report.estimated_margin_account_currency),10
        )
        self.assertFalse(report.can_submit_orders)
        self.assertIn("EXECUCAO_DE_ORDENS_DESABILITADA",report.blockers)
        self.assertIn("SESSOES_FERIADOS_NAO_VERIFICADOS",report.blockers)
        self.assertNotIn("COTACAO_RECENTE_NAO_CONCILIADA",report.blockers)
        self.assertNotIn("order_send",mt5.calls)

    def test_real_account_refused_before_symbol_info(self):
        mt5=FakeMT5()
        mt5.acc.trade_mode=2
        with self.assertRaisesRegex(RuntimeError,"somente conta DEMO"):
            probe_research_signal(mt5,signal(),snapshot(),now=NOW)
        self.assertEqual(mt5.calls,["account_info"])

    def test_wrong_server_refused_before_symbol_info(self):
        mt5=FakeMT5()
        mt5.acc.server="Another-Server"
        with self.assertRaisesRegex(RuntimeError,"Servidor diferente"):
            probe_research_signal(mt5,signal(),snapshot(),now=NOW)
        self.assertEqual(mt5.calls,["account_info"])

    def test_expired_signal_prevents_native_broker_calculations(self):
        mt5=FakeMT5()
        old=signal(candle_closed_at=NOW-timedelta(minutes=7))
        report=probe_research_signal(mt5,old,snapshot(),now=NOW)
        self.assertIn("SINAL_M5_ANTIGO_OU_FUTURO",report.blockers)
        self.assertNotIn("order_calc_profit",mt5.calls)

    def test_distant_price_blocks_old_signal_entry(self):
        mt5=FakeMT5()
        altered=signal(
            entry=90,stop=89,target=92.5,rr=2.5
        )
        report=probe_research_signal(mt5,altered,snapshot(),now=NOW)
        self.assertIn("PRECO_DISTANTE_DA_ENTRADA_TEORICA",report.blockers)
        self.assertNotIn("order_calc_profit",mt5.calls)

    def test_snapshot_wrong_symbol_cannot_be_used(self):
        report=probe_research_signal(
            FakeMT5(),signal(),snapshot(symbol="US100Cash"),now=NOW
        )
        self.assertEqual(report.blockers,("ATIVO_DO_SINAL_DIVERGENTE",))

    def test_minimum_volume_unknown_is_not_fabricated(self):
        mt5=FakeMT5()
        mt5.spec.volume_min=None
        report=probe_research_signal(mt5,signal(),snapshot(),now=NOW)
        self.assertEqual(report.blockers,("LOTE_MINIMO_MT5_INDISPONIVEL",))

    def test_broker_rejects_unaligned_stop_instead_of_rounding_it(self):
        mt5=FakeMT5()
        stop=99.005
        entry=100.2
        target=103.2
        record=signal(stop=stop,rr=(target-entry)/(entry-stop))
        report=probe_research_signal(mt5,record,snapshot(),now=NOW)
        self.assertIn("STOP_ALVO_DESALINHADOS_TICK",report.blockers)
        self.assertFalse(report.can_submit_orders)

    def test_untrusted_quote_and_atr_block_probing(self):
        mt5=FakeMT5()
        for fields,reason in (
            (dict(m5_atr_price=None),"ATR_M5_AUSENTE"),
            (dict(quote_bid=120,quote_ask=119),"COTACAO_ATUAL_INVALIDA"),
        ):
            with self.subTest(fields=fields):
                report=probe_research_signal(
                    mt5,signal(),snapshot(**fields),now=NOW
                )
                self.assertIn(reason,report.blockers)

    def test_timeframe_not_m5_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"M5"):
            probe_research_signal(
                FakeMT5(),signal(timeframe="M15"),snapshot(),now=NOW
            )

    def test_live_monitor_keeps_smc_signal_if_preflight_unavailable(self):
        from smc_agent import adapters
        mt5=FakeMT5()
        record=signal()
        snap=snapshot(record=record)
        class FakeAdapter:
            def __init__(self,sym): self.symbol=sym
        with patch.object(adapters,"MT5Adapter",FakeAdapter), \
             patch("smc_agent.multi_monitor.capture",return_value=snap), \
             patch("smc_agent.multi_monitor.probe_research_signal",
                   side_effect=RuntimeError("Fake broker failure")):
            row=observe_one(mt5,"GOLD")
        self.assertIs(row.snapshot.record,record)
        self.assertIsNone(row.signal_preflight)
        self.assertIsNone(row.error)

    def test_switch_to_real_account_during_optional_preflight_discards_signal(self):
        from smc_agent import adapters
        mt5=FakeMT5()
        snap=snapshot(record=signal())
        class FakeAdapter:
            def __init__(self,sym): self.symbol=sym
        def unexpected_switch(*_args,**_kwargs):
            mt5.acc.trade_mode=2
            raise RuntimeError("Account changed during optional diagnostic")
        with patch.object(adapters,"MT5Adapter",FakeAdapter), \
             patch("smc_agent.multi_monitor.capture",return_value=snap), \
             patch("smc_agent.multi_monitor.probe_research_signal",
                   side_effect=unexpected_switch):
            row=observe_one(mt5,"GOLD")
        self.assertIsNone(row.snapshot)
        self.assertIn("DEMO",row.error)
        self.assertIsNone(row.signal_preflight)

    def test_live_monitor_attaches_broker_preflight_when_smc_signal_present(self):
        from smc_agent import adapters
        mt5=FakeMT5()
        record=signal()
        snap=snapshot(record=record)
        class FakeAdapter:
            def __init__(self,sym): self.symbol=sym
        with patch.object(adapters,"MT5Adapter",FakeAdapter), \
             patch("smc_agent.multi_monitor.capture",return_value=snap), \
             patch("smc_agent.multi_monitor.probe_research_signal",
                   return_value="FAKE-REPORT") as spy:
            row=observe_one(mt5,"GOLD")
        self.assertEqual(row.signal_preflight,"FAKE-REPORT")
        spy.assert_called_once()
        self.assertIsNone(row.error)


if __name__=="__main__":
    unittest.main()
