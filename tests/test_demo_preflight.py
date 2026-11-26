"""XM DEMO native-broker risk preflight using a fake MT5 — NO order_send."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from smc_agent.demo_preflight import (
    BrokerSafetyLimits, DemoOrderHypothesis, estimate_demo_order,
)

D = Decimal
NOW = datetime(2026,11,26,17,30,tzinfo=timezone.utc)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    SYMBOL_TRADE_MODE_FULL=4
    ORDER_TYPE_BUY=0
    ORDER_TYPE_SELL=1

    def __init__(self):
        self.calls=[]
        self.account=SimpleNamespace(
            server="XMGlobal-MT5 5",trade_mode=0,
            currency="USD",equity=10000.0,margin_free=8000.0,
            trade_allowed=True,trade_expert=True
        )
        self.spec=SimpleNamespace(
            trade_mode=4,volume_min=.01,volume_max=50,
            volume_step=.01,trade_tick_size=.01,point=.01,
            trade_stops_level=20
        )
        self.tick=SimpleNamespace(bid=100.0,ask=100.2)
        self.positions=()
        self.orders=()
        self.profit_error=False
        self.margin_error=False

    def account_info(self):
        self.calls.append("account_info")
        return self.account
    def positions_get(self):
        self.calls.append("positions_get")
        return self.positions
    def orders_get(self):
        self.calls.append("orders_get")
        return self.orders
    def symbol_select(self,symbol,visible):
        self.calls.append(("symbol_select",symbol,visible))
        return True
    def symbol_info(self,symbol):
        self.calls.append(("symbol_info",symbol))
        return self.spec
    def symbol_info_tick(self,symbol):
        self.calls.append(("symbol_info_tick",symbol))
        return self.tick
    def order_calc_profit(self,side,symbol,lots,entry,stop):
        self.calls.append("order_calc_profit")
        if self.profit_error:
            return None
        return ((stop-entry) if side == 0 else (entry-stop))*lots*100
    def order_calc_margin(self,side,symbol,lots,entry):
        self.calls.append("order_calc_margin")
        if self.margin_error:
            return None
        return lots*1000
    def order_send(self,*args,**kwargs):
        raise AssertionError("NOT ALLOWED: no actual or demo orders")
    def order_check(self,*args,**kwargs):
        raise AssertionError("NOT ALLOWED: no order-check requests")


def intent(**changes):
    fields=dict(signal_id="synthetic-1",symbol="GOLD",side="buy",
                volume=D("0.10"),stop=D("99.00"),target=D("102.50"))
    fields.update(changes)
    return DemoOrderHypothesis(**fields)


class BrokerNativeDemoPreflightTests(unittest.TestCase):
    def test_normal_demo_returns_money_in_actual_currency_but_never_permission(self):
        mt5=FakeMT5()
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertEqual(report.account_currency,"USD")
        self.assertEqual(report.theoretical_loss_account_currency,D("12.000"))
        self.assertEqual(report.estimated_margin_account_currency,D("100.0"))
        self.assertEqual(report.max_risk_budget_account_currency,D("50.000"))
        self.assertEqual(report.number_open_positions,0)
        self.assertEqual(report.number_pending_orders,0)
        self.assertEqual(report.blockers,(
            "SESSOES_FERIADOS_NAO_VERIFICADOS",
            "EXECUCAO_DE_ORDENS_DESABILITADA",
        ))
        self.assertFalse(report.can_submit_orders)
        self.assertNotIn("order_send",mt5.calls)
        self.assertNotIn("order_check",mt5.calls)

    def test_real_account_refused_before_any_symbol_or_position_read(self):
        mt5=FakeMT5()
        mt5.account.trade_mode=2
        with self.assertRaisesRegex(RuntimeError,"somente conta DEMO"):
            estimate_demo_order(mt5,intent(),now=NOW)
        self.assertEqual(mt5.calls,["account_info"])

    def test_wrong_server_refused_before_market_reads(self):
        mt5=FakeMT5()
        mt5.account.server="Another-Broker"
        with self.assertRaisesRegex(RuntimeError,"Servidor diferente"):
            estimate_demo_order(mt5,intent(),now=NOW)
        self.assertEqual(mt5.calls,["account_info"])

    def test_unavailable_equity_fails_closed(self):
        mt5=FakeMT5()
        mt5.account.equity=0
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertIn("EQUITY_OU_MARGEM_INDISPONIVEIS",report.blockers)
        self.assertNotIn("order_calc_profit",mt5.calls)

    def test_missing_positions_or_orders_cannot_be_treated_as_empty(self):
        for attr in ("positions","orders"):
            mt5=FakeMT5()
            setattr(mt5,attr,None)
            report=estimate_demo_order(mt5,intent(),now=NOW)
            self.assertIn("POSICOES_OU_ORDENS_NAO_CONSULTAVEIS",report.blockers)
            self.assertFalse(report.can_submit_orders)

    def test_existing_position_or_pending_order_blocks_unreconciled_exposure(self):
        for attr in ("positions","orders"):
            mt5=FakeMT5()
            setattr(mt5,attr,(object(),))
            report=estimate_demo_order(mt5,intent(),now=NOW)
            self.assertIn("EXPOSICAO_EXISTENTE_REQUER_RECONCILIACAO",report.blockers)
            self.assertFalse(report.can_submit_orders)

    def test_broker_risk_more_than_equity_limit_blocks(self):
        mt5=FakeMT5()
        report=estimate_demo_order(mt5,intent(volume=D("1")),now=NOW)
        self.assertIn("RISCO_TEORICO_MAIS_RESERVA_EXCEDE_LIMITE",report.blockers)

    def test_margin_limit_blocks_large_usage(self):
        mt5=FakeMT5()
        mt5.account.margin_free=100
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertIn("MARGEM_ESTIMADA_EXCEDE_LIMITE",report.blockers)

    def test_sell_uses_bid_and_above_stop(self):
        mt5=FakeMT5()
        report=estimate_demo_order(
            mt5,intent(side="sell",stop=D("101"),target=D("98")),now=NOW
        )
        self.assertEqual(report.entry_bid,D("100.0"))
        self.assertEqual(report.theoretical_loss_account_currency,D("10.00"))
        self.assertFalse(report.can_submit_orders)

    def test_wrong_stop_target_or_tick_grid_is_blocked(self):
        mt5=FakeMT5()
        report=estimate_demo_order(
            mt5,intent(stop=D("100.10"),target=D("100.30")),now=NOW
        )
        self.assertIn("STOP_ALVO_INCOMPATIVEIS_COMPRA",report.blockers)
        report=estimate_demo_order(
            mt5,intent(stop=D("99.005")),now=NOW
        )
        self.assertIn("STOP_ALVO_DESALINHADOS_TICK",report.blockers)

    def test_broker_stop_level_is_checked_on_opposite_quote(self):
        mt5=FakeMT5()
        mt5.spec.trade_stops_level=50
        report=estimate_demo_order(
            mt5,intent(stop=D("99.60")),now=NOW
        )
        self.assertIn("STOP_ALVO_MUITO_PROXIMOS",report.blockers)

    def test_broker_profit_and_margin_read_fail_closed(self):
        mt5=FakeMT5()
        mt5.profit_error=True
        mt5.margin_error=True
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertIn("CALCULO_PERDA_MT5_INDISPONIVEL",report.blockers)
        self.assertIn("CALCULO_MARGEM_MT5_INDISPONIVEL",report.blockers)

    def test_nontradeable_symbol_and_disabled_account_detected(self):
        mt5=FakeMT5()
        mt5.spec.trade_mode=1
        mt5.account.trade_allowed=False
        mt5.account.trade_expert=False
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertIn("MODO_ATIVO_NAO_NEGOCIAVEL",report.blockers)
        self.assertIn("CONTA_SEM_NEGOCIACAO_AUTORIZADA",report.blockers)
        self.assertIn("AUTOTRADING_DESATIVADO",report.blockers)

    def test_volume_step_min_and_max_verified(self):
        mt5=FakeMT5()
        for lot,block in (
            (D("0.005"),"VOLUME_FORA_DA_FAIXA"),
            (D("0.015"),"VOLUME_FORA_DO_PASSO"),
            (D("60"),"VOLUME_FORA_DA_FAIXA")
        ):
            with self.subTest(lot=lot):
                out=estimate_demo_order(mt5,intent(volume=lot),now=NOW)
                self.assertIn(block,out.blockers)

    def test_missing_symbol_or_quote_fails_closed(self):
        mt5=FakeMT5()
        mt5.spec=None
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertIn("CONTRATO_INDISPONIVEL",report.blockers)
        mt5=FakeMT5()
        mt5.tick=None
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertIn("COTACAO_NAO_DISPONIVEL",report.blockers)

    def test_account_currency_is_used_not_assumed_usd(self):
        mt5=FakeMT5()
        mt5.account.currency="BRL"
        report=estimate_demo_order(mt5,intent(),now=NOW)
        self.assertEqual(report.account_currency,"BRL")
        self.assertEqual(report.theoretical_loss_account_currency,D("12.000"))
        # Fake engine has no FX conversion, real MT5 order_calc_profit does.

    def test_invalid_hypotheses_and_safety_limits_rejected(self):
        with self.assertRaises(ValueError):
            intent(side="hold")
        with self.assertRaises(ValueError):
            intent(volume=D("0"))
        with self.assertRaises(ValueError):
            BrokerSafetyLimits(max_risk_equity_fraction=D("2"))
        with self.assertRaises(ValueError):
            BrokerSafetyLimits(max_margin_free_fraction=D("-0.1"))
        with self.assertRaises(ValueError):
            estimate_demo_order(FakeMT5(),intent(),
                                now=datetime(2026,11,26,17))

    def test_preflight_report_cannot_be_forged_into_authorization(self):
        mt5=FakeMT5()
        report=estimate_demo_order(mt5,intent(),now=NOW)
        with self.assertRaisesRegex(ValueError,"jamais autoriza"):
            replace(report,can_submit_orders=True)


if __name__=="__main__":
    unittest.main()
