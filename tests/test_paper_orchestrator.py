"""Full fictional risk->paper->outcome->SQLite flow; zero brokerage calls."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import unittest

from smc_agent.multi_risk import (
    HypotheticalLimits, HypotheticalPortfolio, ResearchContract
)
from smc_agent.order_intent_journal import ResearchIntentJournal
from smc_agent.paper_execution import PaperIntent, PaperQuote, PaperOutcome
from smc_agent.paper_orchestrator import (
    OfflineAutonomousPaperLab, fabricated_autonomous_cycle
)

T=datetime(2026,11,26,18,tzinfo=timezone.utc)


def contract(symbol="GOLD",**kwargs):
    args=dict(
        symbol=symbol,currency_for_tick_value="USD",
        tick_size=D("0.01"),tick_value_loss_per_lot=D("1"),
        volume_min=D("0.01"),volume_max=D("5"),
        volume_step=D("0.01")
    )
    args.update(kwargs)
    return ResearchContract(**args)


def limits(**kwargs):
    args=dict(equity=D("10000"),currency="USD")
    args.update(kwargs)
    return HypotheticalLimits(**args)


def quote(*,symbol="GOLD",seconds=0,bid=100,ask=100.2):
    return PaperQuote(symbol,T+timedelta(seconds=seconds),bid,ask)


def plan(signal_id="research-001",symbol="GOLD",side="buy",
         stop=99,target=102):
    return PaperIntent(signal_id,symbol,side,stop,target)


class PaperOrchestrationTests(unittest.TestCase):
    def test_fictional_autonomous_cycle_from_risk_through_target(self):
        out=fabricated_autonomous_cycle()
        self.assertEqual(out["data"],"INVENTADOS")
        self.assertEqual(out["outcome"],"ALVO_OBSERVADO")
        self.assertEqual(out["journal_terminal_state"],"SIMULATED_TARGET_OBSERVED")
        self.assertEqual(out["orders_sent"],0)
        self.assertTrue(out["duplicate_stopped"])
        self.assertEqual(out["unresolved_after_restart"],0)
        self.assertAlmostEqual(out["price_difference"],1.9)

    def test_open_and_close_buy_uses_ask_then_bid_and_terminal_journal(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            p=plan()
            out=lab.prepare_and_open_paper(p,quote(),contract(),limits())
            self.assertEqual(out.status,"PAPER_POSITION_OPEN")
            self.assertEqual(out.orders_sent,0)
            self.assertGreater(out.research_risk.research_lots,D("0"))
            self.assertEqual(out.simulated_position.entry_price,100.2)
            done=lab.observe_paper(
                p.signal_id,quote(seconds=1,bid=102.1,ask=102.3)
            )
            self.assertIsInstance(done,PaperOutcome)
            self.assertEqual(done.outcome,"ALVO_OBSERVADO")
            self.assertEqual(journal.state(p.signal_id),"SIMULATED_TARGET_OBSERVED")
            self.assertEqual(lab.open_paper_positions(),0)

    def test_sell_stop_uses_opposite_ask_price(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            p=plan(side="sell",stop=101,target=98)
            out=lab.prepare_and_open_paper(p,quote(),contract(),limits())
            self.assertEqual(out.status,"PAPER_POSITION_OPEN")
            done=lab.observe_paper(
                p.signal_id,quote(seconds=1,bid=102.0,ask=102.2)
            )
            self.assertEqual(done.outcome,"STOP_OBSERVADO")
            self.assertAlmostEqual(done.pnl_price_units,-2.2)
            self.assertEqual(journal.state(p.signal_id),"SIMULATED_STOP_OBSERVED")

    def test_gapped_paper_quote_is_inconclusive_not_profitable(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal,max_quote_gap_seconds=2)
            p=plan()
            lab.prepare_and_open_paper(p,quote(),contract(),limits())
            outcome=lab.observe_paper(
                p.signal_id,quote(seconds=15,bid=105,ask=105.2)
            )
            self.assertEqual(outcome.outcome,"COBERTURA_INSUFICIENTE")
            self.assertIsNone(outcome.pnl_price_units)
            self.assertEqual(journal.state(p.signal_id),"SIMULATED_GAP_INCONCLUSIVE")

    def test_repeated_signal_does_not_open_second_paper_position(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            p=plan()
            lab.prepare_and_open_paper(p,quote(),contract(),limits())
            report=lab.prepare_and_open_paper(
                p,quote(seconds=1),contract(),limits()
            )
            self.assertEqual(report.status,"BLOQUEADO")
            self.assertIn("SINAL_DUPLICADO",report.block_codes)
            self.assertEqual(lab.open_paper_positions(),1)

    def test_open_paper_position_counts_toward_symbol_exposure(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            lab.prepare_and_open_paper(plan(),quote(),contract(),limits())
            report=lab.prepare_and_open_paper(
                plan("research-002"),
                quote(seconds=1),contract(),limits()
            )
            self.assertEqual(report.status,"BLOQUEADO")
            self.assertIn("LIMITE_POSICOES_POR_ATIVO",report.block_codes)
            self.assertEqual(lab.open_paper_positions(),1)

    def test_existing_paper_position_reduces_budget_for_other_asset(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            first=lab.prepare_and_open_paper(
                plan(),quote(),contract(),limits()
            )
            second=lab.prepare_and_open_paper(
                plan("us100-001",symbol="US100Cash"),
                quote(symbol="US100Cash",seconds=1),
                contract("US100Cash"),
                limits(max_trade_amount=D("60"),
                       max_portfolio_reserved=D("30")),
            )
            self.assertEqual(first.status,"PAPER_POSITION_OPEN")
            self.assertEqual(second.status,"PAPER_POSITION_OPEN")
            self.assertLessEqual(
                second.research_risk.illustrative_total,
                D("30")-first.research_risk.illustrative_total
            )

    def test_loss_limit_and_kill_switch_block_risk_before_reserving_id(self):
        for state,reason in (
            (HypotheticalPortfolio(emergency_stop=True),"PARADA_EMERGENCIA_ATIVA"),
            (HypotheticalPortfolio(connection_healthy=False),"CONEXAO_NAO_CONFIAVEL"),
            (HypotheticalPortfolio(realized_loss_today=D("200")),
             "PERDA_DIARIA_OU_RESERVAS_NO_LIMITE"),
        ):
            with self.subTest(reason=reason):
                with ResearchIntentJournal(":memory:") as journal:
                    lab=OfflineAutonomousPaperLab(journal)
                    report=lab.prepare_and_open_paper(
                        plan(),quote(),contract(),limits(),
                        external_hypothetical_portfolio=state
                    )
                    self.assertEqual(report.status,"BLOQUEADO")
                    self.assertIn(reason,report.block_codes)
                    self.assertIsNone(journal.state("research-001"))
                    self.assertEqual(report.orders_sent,0)

    def test_bad_contract_currency_blocks_without_position(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            report=lab.prepare_and_open_paper(
                plan(),quote(),
                contract(currency_for_tick_value="EUR"),limits()
            )
            self.assertEqual(report.status,"BLOQUEADO")
            self.assertIn("MOEDA_VALOR_TICK_NAO_COMPATIVEL",report.block_codes)
            self.assertEqual(lab.open_paper_positions(),0)

    def test_wrong_symbol_prevents_journal_write(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            report=lab.prepare_and_open_paper(
                plan(),quote(symbol="US100Cash"),contract(),limits()
            )
            self.assertEqual(report.block_codes,("ATIVO_DIVERGENTE",))
            self.assertIsNone(journal.state("research-001"))

    def test_restart_quarantines_open_paper_and_refuses_duplicate_id(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"research.sqlite3"
            with ResearchIntentJournal(path) as journal:
                lab=OfflineAutonomousPaperLab(journal)
                opened=lab.prepare_and_open_paper(
                    plan(),quote(),contract(),limits()
                )
                self.assertEqual(opened.status,"PAPER_POSITION_OPEN")
            with ResearchIntentJournal(path) as journal:
                restarted=OfflineAutonomousPaperLab(journal)
                self.assertEqual(
                    restarted.prepare_after_restart(at=T+timedelta(seconds=1)),1
                )
                self.assertEqual(journal.state("research-001"),
                                 "RECONCILE_REQUIRED")
                result=restarted.prepare_and_open_paper(
                    plan(),quote(seconds=2),contract(),limits()
                )
                self.assertEqual(result.block_codes,("ID_JA_RESERVADO_EM_DISCO",))
                self.assertEqual(restarted.open_paper_positions(),0)

    def test_error_in_paper_open_is_journaled_as_blocked(self):
        with ResearchIntentJournal(":memory:") as journal:
            lab=OfflineAutonomousPaperLab(journal)
            p=plan(stop=99,target=100.1) # target lower than long Ask
            with self.assertRaisesRegex(ValueError,"Stop / target"):
                lab.prepare_and_open_paper(
                    p,quote(),contract(),limits()
                )
            self.assertEqual(journal.state(p.signal_id),"BLOCKED_RESEARCH")
            self.assertEqual(lab.open_paper_positions(),0)

    def test_cli_smoke_test_runs_without_broker(self):
        result=subprocess.run(
            [sys.executable,"-m","smc_agent.paper_orchestrator"],
            capture_output=True,text=True,timeout=20
        )
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("CICLO AUTONOMO FICTICIO",result.stdout)
        self.assertIn("SEM MT5, SEM ORDENS",result.stdout)
        self.assertIn("SIMULATED_TARGET_OBSERVED",result.stdout)


if __name__=="__main__":
    unittest.main()
