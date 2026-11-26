"""Offline v0.14 tests: ALL money, market data and state are invented."""
from dataclasses import replace
from decimal import Decimal
import subprocess
import sys
import unittest

from smc_agent.multi_risk import (
    HypotheticalLimits, HypotheticalPortfolio, ResearchContract,
    ResearchIntent, ResearchRiskDecision, calculate_hypothetical_size,
    fabricated_example
)

D = Decimal


def contract(**changes):
    fields = dict(
        symbol="GOLD", currency_for_tick_value="USD",
        tick_size=D(".01"), tick_value_loss_per_lot=D("1"),
        volume_min=D(".01"), volume_max=D("50"), volume_step=D(".001"),
    )
    fields.update(changes)
    return ResearchContract(**fields)


def intent(**changes):
    fields = dict(
        signal_id="synthetic-1", symbol="GOLD", side="buy",
        bid=D("100"), ask=D("100.20"), stop=D("99"),
    )
    fields.update(changes)
    return ResearchIntent(**fields)


def limits(**changes):
    fields = dict(equity=D("10000"), currency="USD")
    fields.update(changes)
    return HypotheticalLimits(**fields)


class MultiAssetResearchRiskTests(unittest.TestCase):
    def test_buy_risk_size_never_exceeds_budget(self):
        out=calculate_hypothetical_size(intent(),contract(),limits())
        self.assertEqual(out.status,"PESQUISA_APENAS")
        self.assertEqual(out.research_lots,D(".195"))
        self.assertEqual(out.theoretical_loss_to_stop,D("23.400"))
        self.assertEqual(out.illustrative_cost_reserve,D("1.585"))
        self.assertEqual(out.illustrative_total,D("24.985"))
        self.assertEqual(out.available_budget,D("25"))
        self.assertFalse(out.can_submit_orders)

    def test_sell_uses_bid_as_entry_and_stop_above_it(self):
        out=calculate_hypothetical_size(
            intent(side="sell",bid=D("100"),ask=D("100.30"),stop=D("101")),
            contract(),limits()
        )
        self.assertEqual(out.status,"PESQUISA_APENAS")
        self.assertGreater(out.research_lots,D("0"))
        self.assertEqual(out.illustrative_total,
                         out.theoretical_loss_to_stop+out.illustrative_cost_reserve)

    def test_forex_uses_its_own_tick_units_not_gold(self):
        out=calculate_hypothetical_size(
            intent(symbol="EURUSD",bid=D("1.08000"),ask=D("1.08012"),
                   stop=D("1.07912")),
            contract(symbol="EURUSD",tick_size=D("0.00001"),
                     tick_value_loss_per_lot=D("1")),
            limits()
        )
        self.assertEqual(out.status,"PESQUISA_APENAS")
        self.assertEqual(out.available_budget,D("25"))
        self.assertLessEqual(out.illustrative_total,out.available_budget)

    def test_us100_tick_price_and_minimum_volume_are_unique(self):
        out=calculate_hypothetical_size(
            intent(symbol="US100Cash",bid=D("20000"),ask=D("20003"),
                   stop=D("19980")),
            contract(symbol="US100Cash",tick_size=D("0.1"),
                     tick_value_loss_per_lot=D("1"),volume_min=D(".1"),
                     volume_step=D(".1")),
            limits()
        )
        self.assertEqual(out.research_lots,D(".1"))
        self.assertLessEqual(out.illustrative_total,D("25"))

    def test_min_lot_over_budget_returns_no_position(self):
        out=calculate_hypothetical_size(
            intent(stop=D("60")),contract(volume_min=D(".1")),
            limits(equity=D("1000"))
        )
        self.assertEqual(out.status,"BLOQUEADO")
        self.assertEqual(out.block_codes,("LOTE_MINIMO_EXCEDE_ORCAMENTO",))
        self.assertIsNone(out.research_lots)

    def test_currency_mismatch_fails_closed(self):
        out=calculate_hypothetical_size(
            intent(),contract(currency_for_tick_value="EUR"),limits()
        )
        self.assertIn("MOEDA_VALOR_TICK_NAO_COMPATIVEL",out.block_codes)
        self.assertIsNone(out.research_lots)

    def test_no_other_asset_can_reuse_gold_contract(self):
        out=calculate_hypothetical_size(
            intent(symbol="US500Cash"),contract(),limits()
        )
        self.assertIn("SIMBOLO_DIVERGENTE",out.block_codes)

    def test_hard_daily_loss_cap_including_reserved_risk(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(),
            HypotheticalPortfolio(realized_loss_today=D("190"),
                                  reserved_estimated_loss=D("10"))
        )
        self.assertIn("PERDA_DIARIA_OU_RESERVAS_NO_LIMITE",out.block_codes)
        self.assertEqual(out.available_budget,D("0"))

    def test_partial_daily_losses_reduce_room_and_lot_size(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(max_trade_amount=D("80"),
                                       max_portfolio_reserved=D("80")),
            HypotheticalPortfolio(realized_loss_today=D("170"))
        )
        self.assertEqual(out.available_budget,D("30"))
        self.assertLessEqual(out.illustrative_total,D("30"))

    def test_portfolio_reservations_reduce_remaining_budget(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(),
            HypotheticalPortfolio(reserved_estimated_loss=D("50"),
                                  active_symbols=("US100Cash",))
        )
        self.assertEqual(out.available_budget,D("10"))
        self.assertLessEqual(out.illustrative_total,D("10"))

    def test_fully_reserved_portfolio_blocks(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(),
            HypotheticalPortfolio(reserved_estimated_loss=D("60"))
        )
        self.assertIn("EXPOSICAO_RESERVADA_NO_LIMITE",out.block_codes)

    def test_one_active_position_per_symbol(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(),
            HypotheticalPortfolio(active_symbols=("GOLD",))
        )
        self.assertIn("LIMITE_POSICOES_POR_ATIVO",out.block_codes)

    def test_limit_all_simultaneous_positions(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(),
            HypotheticalPortfolio(active_symbols=("US100Cash","US500Cash"))
        )
        self.assertIn("LIMITE_POSICOES_SIMULTANEAS",out.block_codes)

    def test_emergency_kill_switch_and_connection_loss(self):
        for state,code in (
            (HypotheticalPortfolio(emergency_stop=True),"PARADA_EMERGENCIA_ATIVA"),
            (HypotheticalPortfolio(connection_healthy=False),"CONEXAO_NAO_CONFIAVEL"),
        ):
            with self.subTest(code=code):
                out=calculate_hypothetical_size(intent(),contract(),limits(),state)
                self.assertIn(code,out.block_codes)
                self.assertIsNone(out.research_lots)

    def test_duplicate_signal_id_is_blocked(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(),
            HypotheticalPortfolio(seen_signal_ids=frozenset({"synthetic-1"}))
        )
        self.assertIn("SINAL_DUPLICADO",out.block_codes)

    def test_unaligned_stop_is_rejected_rather_than_rounded(self):
        out=calculate_hypothetical_size(
            intent(stop=D("99.005")),contract(),limits()
        )
        self.assertEqual(out.block_codes,("STOP_FORA_TICK_SIZE",))

    def test_nonmultiple_minimum_uses_min_plus_steps(self):
        out=calculate_hypothetical_size(
            intent(),contract(volume_min=D(".01"),volume_step=D(".003")),limits()
        )
        self.assertEqual(out.status,"PESQUISA_APENAS")
        self.assertEqual((out.research_lots-D(".01"))%D(".003"),D("0"))
        self.assertLessEqual(out.illustrative_total,out.available_budget)

    def test_fixed_reserve_exceeds_budget_blocks(self):
        out=calculate_hypothetical_size(
            intent(),contract(),limits(equity=D("1000"),
                                       fixed_cost_reserve=D("5"))
        )
        self.assertEqual(out.block_codes,("ORCAMENTO_NAO_COBRE_RESERVA",))

    def test_invalid_contract_and_limits_rejected(self):
        with self.assertRaises(ValueError):
            contract(tick_value_loss_per_lot=D("0"))
        with self.assertRaises(ValueError):
            contract(currency_for_tick_value="UNKNOWN")
        with self.assertRaises(ValueError):
            contract(volume_min=D("1"),volume_max=D(".1"))
        with self.assertRaises(ValueError):
            limits(risk_fraction_per_trade=D("2"))
        with self.assertRaises(ValueError):
            limits(equity=D("NaN"))
        with self.assertRaises(ValueError):
            limits(max_positions=0)
        with self.assertRaises(ValueError):
            limits(max_positions_per_symbol=3)

    def test_invalid_portfolio_state_rejected(self):
        with self.assertRaises(ValueError):
            HypotheticalPortfolio(realized_loss_today=D("-5"))
        with self.assertRaises(ValueError):
            HypotheticalPortfolio(reserved_estimated_loss=D("-1"))
        with self.assertRaises(ValueError):
            HypotheticalPortfolio(connection_healthy=1)
        with self.assertRaises(ValueError):
            HypotheticalPortfolio(active_symbols=("GOLD",False))

    def test_crossed_quotes_and_invalid_stop_rejected(self):
        with self.assertRaises(ValueError):
            intent(bid=D("101"),ask=D("100"))
        with self.assertRaises(ValueError):
            intent(stop=D("101"))
        with self.assertRaises(ValueError):
            intent(side="sell",stop=D("99"))
        with self.assertRaises(ValueError):
            intent(side="hold")

    def test_decision_never_can_enable_broker_execution(self):
        out=calculate_hypothetical_size(intent(),contract(),limits())
        with self.assertRaisesRegex(ValueError,"never authorizes"):
            replace(out,can_submit_orders=True)

    def test_cli_runs_completely_offline(self):
        example=fabricated_example()
        self.assertIn("DADOS INVENTADOS",example)
        self.assertIn("Ordens enviadas: 0",example)
        r=subprocess.run(
            [sys.executable,"-m","smc_agent.multi_risk"],
            capture_output=True,text=True,timeout=15
        )
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("Execucao automatica: BLOQUEADA",r.stdout)


if __name__ == "__main__":
    unittest.main()
