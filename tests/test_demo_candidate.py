"""Read-only live demo signal -> native risk -> MT5 request preview tests.

Fake MT5 objects purposely implement order_send as an ASSERTION FAILURE:
none of these tests may transmit any actual or demo order.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from smc_agent.alerts import SignalRecord
from smc_agent.monitor_local import MonitorSnapshot
from smc_agent.demo_candidate import build_demo_open_candidate

NOW=datetime(2026,11,26,17,30,tzinfo=timezone.utc)


def signal(**changes):
    fields=dict(
        event_id="SMC-SYN-01",symbol="GOLD",timeframe="M5",
        candle_closed_at=NOW-timedelta(seconds=60),
        side="buy",entry=100.2,stop=99.0,target=103.2,
        rr=2.5,reason="fictional",source="fixture",
    )
    fields.update(changes)
    return SignalRecord(**fields)


def snapshot(**changes):
    data=dict(
        generated_utc=(NOW-timedelta(seconds=1)).isoformat(),
        symbol="GOLD",server="XMGlobal-MT5 5",connected_to_demo=True,
        state="SINAL DE PESQUISA",
        quote_time_utc=(NOW-timedelta(seconds=2)).isoformat(),
        quote_bid=100.0,quote_ask=100.2,
        m5_atr_price=4.0,
        clock_offset_label="UTC+02:00 (observado agora, provisório)"
    )
    data.update(changes)
    return MonitorSnapshot(**data)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    SYMBOL_TRADE_MODE_FULL=4
    TRADE_ACTION_DEAL=1
    ORDER_TYPE_BUY=0
    ORDER_TYPE_SELL=1
    ORDER_TIME_GTC=0
    # MT5 SYMBOL_FILLING_* bit flags and ORDER_FILLING_* enums DIFFER!
    SYMBOL_FILLING_FOK=1
    SYMBOL_FILLING_IOC=2
    ORDER_FILLING_FOK=0
    ORDER_FILLING_IOC=1

    def __init__(self):
        self.calls=[]
        self.flip_real_on=None
        self.acc=SimpleNamespace(
            trade_mode=0,server="XMGlobal-MT5 5",
            currency="USD",equity=10000,margin_free=8000,
            trade_allowed=True,trade_expert=True
        )
        self.spec=SimpleNamespace(
            digits=2,trade_mode=4,
            volume_min=.01,volume_max=50,volume_step=.01,
            trade_tick_size=.01,point=.01,trade_stops_level=20,
            filling_mode=2,
        )
        self.orders=()
        self.positions=()
    def account_info(self):
        self.calls.append("account_info")
        if self.flip_real_on and self.calls.count("account_info")>=self.flip_real_on:
            self.acc.trade_mode=2
        return self.acc
    def symbol_info(self,symbol):
        self.calls.append("symbol_info")
        return self.spec
    def symbol_select(self,symbol,visible):
        self.calls.append("symbol_select")
        return True
    def symbol_info_tick(self,symbol):
        self.calls.append("symbol_info_tick")
        return SimpleNamespace(bid=100.0,ask=100.2)
    def positions_get(self):
        self.calls.append("positions_get")
        return self.positions
    def orders_get(self):
        self.calls.append("orders_get")
        return self.orders
    def order_calc_profit(self,side,symbol,volume,entry,stop):
        self.calls.append("order_calc_profit")
        return (stop-entry)*volume*100 if side==0 else (entry-stop)*volume*100
    def order_calc_margin(self,side,symbol,volume,entry):
        self.calls.append("order_calc_margin")
        return 1000*volume
    def order_send(self,*args,**kwargs):
        raise AssertionError("ORDER_SEND MUST NEVER BE CALLED")
    def order_check(self,*args,**kwargs):
        raise AssertionError("ORDER_CHECK MUST NEVER BE CALLED")


class EndToEndDemoCandidateTests(unittest.TestCase):
    def test_buy_creates_no_order_but_native_risk_and_mapped_ioc_draft(self):
        mt5=FakeMT5()
        candidate=build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertIsNotNone(candidate.preview)
        self.assertFalse(candidate.can_submit_orders)
        self.assertFalse(candidate.preview.can_submit_orders)
        fields=candidate.preview.as_dict()
        self.assertEqual(fields["type"],0)
        self.assertEqual(fields["price"],100.2)
        self.assertEqual(fields["sl"],99)
        self.assertEqual(fields["tp"],103.2)
        self.assertEqual(fields["volume"],.01)
        self.assertEqual(fields["type_filling"],1)  # IOC ORDER enum (not flag 2)
        self.assertIn("SESSOES_FERIADOS_NAO_VERIFICADOS",candidate.blockers)
        self.assertIn("EXECUCAO_DE_ORDENS_DESABILITADA",candidate.blockers)
        self.assertAlmostEqual(
            float(candidate.report.theoretical_loss_account_currency),1.2
        )
        self.assertNotIn("order_send",mt5.calls)
        self.assertNotIn("order_check",mt5.calls)

    def test_sell_uses_bid_and_sell_position_direction(self):
        mt5=FakeMT5()
        old=signal()
        entry=100.0
        stop=101.0
        target=97.5
        short=signal(side="sell",entry=entry,stop=stop,target=target,
                     rr=(entry-target)/(stop-entry))
        out=build_demo_open_candidate(mt5,short,snapshot(),now=NOW)
        self.assertIsNotNone(out.preview)
        fields=out.preview.as_dict()
        self.assertEqual(fields["type"],1)
        self.assertEqual(fields["price"],100)
        self.assertEqual(fields["sl"],101)
        self.assertEqual(fields["tp"],97.5)

    def test_fok_is_explicitly_selected_when_ioc_not_supported(self):
        mt5=FakeMT5()
        mt5.spec.filling_mode=1  # FOK bitmask
        result=build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertIsNotNone(result.preview)
        self.assertEqual(result.preview.as_dict()["type_filling"],0)

    def test_unknown_or_boc_only_filling_flags_prevent_request_preview(self):
        for filling in (0,4,None):
            with self.subTest(filling=filling):
                mt5=FakeMT5()
                mt5.spec.filling_mode=filling
                out=build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
                self.assertIsNone(out.preview)
                self.assertIn("PREVIA_BLOQUEADA_INCOMPATIBILIDADE_MT5",out.blockers)

    def test_wrong_order_filling_constant_does_not_use_raw_mask(self):
        mt5=FakeMT5()
        mt5.ORDER_FILLING_IOC=None
        out=build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertIsNone(out.preview)
        self.assertFalse(out.can_submit_orders)

    def test_stale_tick_blocks_request_preview_before_filling_mode(self):
        mt5=FakeMT5()
        old=snapshot(quote_time_utc=(NOW-timedelta(minutes=3)).isoformat())
        out=build_demo_open_candidate(mt5,signal(),old,now=NOW)
        self.assertIsNone(out.preview)
        self.assertIn("PREVIA_NAO_GERADA_FALHA_DADOS",out.blockers)
        self.assertNotIn("order_send",mt5.calls)

    def test_existing_broker_position_requires_reconciliation(self):
        mt5=FakeMT5()
        mt5.positions=(object(),)
        out=build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertIsNone(out.preview)
        self.assertIn("EXPOSICAO_EXISTENTE_REQUER_RECONCILIACAO",out.blockers)

    def test_pending_broker_order_blocks_preview(self):
        mt5=FakeMT5()
        mt5.orders=(object(),)
        out=build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertIsNone(out.preview)
        self.assertIn("EXPOSICAO_EXISTENTE_REQUER_RECONCILIACAO",out.blockers)

    def test_abnormal_spread_versus_atr_prevents_preview(self):
        mt5=FakeMT5()
        out=build_demo_open_candidate(
            mt5,signal(),snapshot(m5_atr_price=.1),now=NOW
        )
        self.assertIsNone(out.preview)
        self.assertIn("SPREAD_ELEVADO_RELATIVO_ATR",out.blockers)

    def test_real_account_refused_before_any_symbol_read(self):
        mt5=FakeMT5()
        mt5.acc.trade_mode=2
        with self.assertRaisesRegex(RuntimeError,"somente conta DEMO"):
            build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertEqual(mt5.calls,["account_info"])

    def test_server_mismatch_refused_before_any_symbol_read(self):
        mt5=FakeMT5()
        mt5.acc.server="XM-Other"
        with self.assertRaisesRegex(RuntimeError,"Servidor diferente"):
            build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertEqual(mt5.calls,["account_info"])

    def test_switch_to_real_account_during_native_read_invalidates_candidate(self):
        mt5=FakeMT5()
        mt5.flip_real_on=4
        with self.assertRaisesRegex(RuntimeError,"somente conta DEMO"):
            build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
        self.assertNotIn("order_send",mt5.calls)

    def test_missing_or_invalid_broker_contract_fields_prevent_preview(self):
        for attr,value in (("trade_tick_size",None),("volume_step",0),
                           ("trade_stops_level",None)):
            with self.subTest(attr=attr):
                mt5=FakeMT5()
                setattr(mt5.spec,attr,value)
                out=build_demo_open_candidate(mt5,signal(),snapshot(),now=NOW)
                self.assertIsNone(out.preview)
                self.assertFalse(out.can_submit_orders)

    def test_invalid_stop_or_target_does_not_get_rounded(self):
        mt5=FakeMT5()
        stop=99.005
        entry=100.2
        target=103.2
        sig=signal(stop=stop,rr=(target-entry)/(entry-stop))
        out=build_demo_open_candidate(mt5,sig,snapshot(),now=NOW)
        self.assertIsNone(out.preview)
        self.assertIn("STOP_ALVO_DESALINHADOS_TICK",out.blockers)

    def test_unverified_clock_never_gives_request_preview(self):
        out=build_demo_open_candidate(
            FakeMT5(),signal(),
            snapshot(clock_offset_label="NAO_VERIFICADO"),now=NOW
        )
        self.assertIsNone(out.preview)
        self.assertIn("RELOGIO_AO_VIVO_NAO_VALIDADO",out.blockers)


if __name__ == "__main__":
    unittest.main()
