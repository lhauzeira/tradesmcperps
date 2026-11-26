"""v0.13 fail-closed pretrade diagnostics — synthetic only, NEVER connects to MT5."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from smc_agent.readiness import ReadinessPolicy, ReadinessReport, evaluate_readiness


def snap(**changes):
    values = dict(
        symbol="GOLD", connected_to_demo=True,
        generated_utc="2026-11-26T15:10:00+00:00",
        quote_time_utc="2026-11-26T15:09:57+00:00",
        clock_offset_label="UTC+02:00 (provisório)",
        quote_bid=3574.32, quote_ask=3574.52,
        m5_atr_price=4.0,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def spec(**changes):
    values = dict(
        trade_mode=4, trade_tick_size=0.01, trade_tick_value=1.0,
        volume_min=0.01, volume_step=0.01, volume_max=50.0, point=0.01,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def assess(s=None, m=None, *, session_verified=False, code=4, policy=None):
    args = dict(
        trade_mode_full=code, session_verified=session_verified
    )
    if policy is not None:
        args["policy"] = policy
    return evaluate_readiness(s or snap(), m or spec(), **args)


class PretradeReadinessTests(unittest.TestCase):
    def test_fresh_broker_data_cannot_authorize_order_without_session(self):
        out=assess()
        self.assertEqual(out.status,"BLOQUEADO_PARA_EXECUCAO")
        self.assertEqual(out.block_codes,("SESSAO_OU_FERIADO_NAO_VERIFICADO",))
        self.assertFalse(out.can_submit_orders)
        self.assertAlmostEqual(out.spread_to_m5_atr, 0.05)
        self.assertAlmostEqual(out.tick_age_seconds,3)

    def test_even_verified_session_cannot_grant_order_permission(self):
        out=assess(session_verified=True)
        self.assertEqual(out.status,"DADOS_PRELIMINARES_APENAS")
        self.assertEqual(out.block_codes,())
        self.assertFalse(out.can_submit_orders)

    def test_result_cannot_be_forged_to_authorize_orders(self):
        with self.assertRaisesRegex(ValueError,"cannot authorize"):
            replace(assess(),can_submit_orders=True)

    def test_old_tick_is_rejected_without_market_hours_inference(self):
        out=assess(snap(quote_time_utc="2026-11-26T15:09:30+00:00"))
        self.assertIn("TICK_DESATUALIZADO_OU_FUTURO",out.block_codes)

    def test_future_tick_is_rejected(self):
        out=assess(snap(quote_time_utc="2026-11-26T15:10:08+00:00"))
        self.assertIn("TICK_DESATUALIZADO_OU_FUTURO",out.block_codes)

    def test_naive_or_missing_timestamp_is_rejected(self):
        for timestamp in ("2026-11-26T15:09:57",None,"garbage"):
            with self.subTest(timestamp=timestamp):
                out=assess(snap(quote_time_utc=timestamp))
                self.assertIn("HORARIO_COTACAO_INVALIDO",out.block_codes)
                self.assertFalse(out.can_submit_orders)

    def test_wrong_or_missing_account_demo_identity(self):
        self.assertIn("CONTA_DEMO_NAO_CONFIRMADA",
                      assess(snap(connected_to_demo=False)).block_codes)
        self.assertIn("RELOGIO_NAO_CONCILIADO",
                      assess(snap(clock_offset_label="NÃO VERIFICADO")).block_codes)

    def test_wide_spread_for_same_asset_relative_to_its_own_atr(self):
        out=assess(snap(quote_ask=3576.00, m5_atr_price=4.0))
        self.assertIn("SPREAD_ELEVADO_RELATIVO_ATR",out.block_codes)
        self.assertAlmostEqual(out.spread_to_m5_atr,0.42)

    def test_forex_price_scale_is_independent(self):
        out=assess(snap(
            symbol="EURUSD",quote_bid=1.08810,quote_ask=1.08822,
            m5_atr_price=0.00100
        ),spec(trade_tick_size=0.00001,trade_tick_value=1.0,point=0.00001))
        self.assertAlmostEqual(out.spread_to_m5_atr,0.12)
        self.assertNotIn("SPREAD_ELEVADO_RELATIVO_ATR",out.block_codes)

    def test_invalid_quote_and_atr_fail_closed(self):
        out=assess(snap(quote_bid=2,quote_ask=1))
        self.assertIn("COTACAO_BID_ASK_INVALIDA",out.block_codes)
        out=assess(snap(m5_atr_price=0.0))
        self.assertIn("ATR_M5_INDISPONIVEL",out.block_codes)

    def test_broker_trade_mode_not_full_blocks_even_if_recent_ticks(self):
        for value in (None,1,2,3,5):
            with self.subTest(value=value):
                out=assess(m=spec(trade_mode=value))
                self.assertIn("MODO_NEGOCIACAO_NAO_CONFIRMADO",out.block_codes)

    def test_missing_tick_value_and_unverified_contract_blocks(self):
        out=assess(m=spec(trade_tick_value=0))
        self.assertIn("CONTRATO_OU_TICK_VALUE_NAO_CONFIRMADO",out.block_codes)
        out=assess(m=spec(volume_min=100,volume_max=50))
        self.assertIn("LIMITES_VOLUME_INCOERENTES",out.block_codes)

    def test_invalid_policy_rejected(self):
        for kw in (dict(max_tick_age_seconds=0),
                   dict(max_tick_age_seconds=float("nan")),
                   dict(max_spread_to_m5_atr=-1),
                   dict(max_future_quote_seconds=False)):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    ReadinessPolicy(**kw)


if __name__ == "__main__":
    unittest.main()
