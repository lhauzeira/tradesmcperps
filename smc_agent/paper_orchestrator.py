"""Integrated, OFFLINE-ONLY autonomous paper lifecycle rehearsal.

Combines the synthetic bid/ask position book, hypothetical per-asset
risk math and durable SQLite idempotency journal. No MT5 imports,
no account access, no order_send, no trading permissions and no real
prices or account returns.

A process restart quarantines any PAPER_POSITION_OPEN in SQLite, rather
than pretending that position can safely resume or repeating an order.
This is a laboratory-only research pipeline, NOT a production execution
engine and does not guarantee that a real stop executes at its level.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .multi_risk import (
    HypotheticalLimits, HypotheticalPortfolio, ResearchContract,
    ResearchIntent, ResearchRiskDecision, calculate_hypothetical_size
)
from .order_intent_journal import ResearchIntentJournal, ResearchOrderIntent
from .paper_execution import (
    PaperIntent, PaperOutcome, PaperPosition, PaperQuote, SyntheticPaperBook
)

VENUE = "XMGlobal-MT5 5 (DEMO-RESEARCH)"


@dataclass(frozen=True)
class PaperStartReport:
    signal_id: str
    status: str
    block_codes: tuple[str, ...]
    research_risk: ResearchRiskDecision | None
    simulated_position: PaperPosition | None
    orders_sent: int = 0

    def __post_init__(self):
        if self.orders_sent != 0:
            raise ValueError("Paper-only pipeline cannot send orders")


class OfflineAutonomousPaperLab:
    """Single-process tick rehearsal; no terminal, execution or credentials.

    Caller passes a hypothetical risk context; this object adds its OWN
    already-open paper positions to avoid omitting their reserved budget.
    A real account's positions and realized losses are NOT accessed.
    """

    def __init__(self, journal: ResearchIntentJournal, *,
                 max_quote_gap_seconds: float = 2):
        self.journal=journal
        self.book=SyntheticPaperBook(max_quote_gap_seconds=max_quote_gap_seconds)
        self._reserved_by_signal: dict[str, Decimal] = {}

    def _with_paper_exposure(
        self, portfolio: HypotheticalPortfolio
    ) -> HypotheticalPortfolio:
        paper_ids=frozenset(self.book.open_positions.keys())
        if portfolio.seen_signal_ids.intersection(paper_ids):
            # Not an execution block: allow caller's already-seen IDs
            # to be reflected alongside local paper positions.
            pass
        paper_symbols=tuple(
            pos.intent.symbol for pos in self.book.open_positions.values()
        )
        reserved=sum(self._reserved_by_signal.values(),Decimal("0"))
        return replace(
            portfolio,
            active_symbols=portfolio.active_symbols + paper_symbols,
            reserved_estimated_loss=portfolio.reserved_estimated_loss + reserved,
            seen_signal_ids=portfolio.seen_signal_ids.union(paper_ids),
        )

    def prepare_and_open_paper(
        self, signal: PaperIntent, quote: PaperQuote,
        contract: ResearchContract, limits: HypotheticalLimits,
        *,
        external_hypothetical_portfolio: HypotheticalPortfolio =
            HypotheticalPortfolio(),
    ) -> PaperStartReport:
        """Create paper entry only when fictional arithmetic can protect it.

        Always reserve the stable signal ID in SQLite before the simulated
        opening. Duplicate/restarted IDs are NEVER reopened.
        """
        if signal.symbol != quote.symbol or signal.symbol != contract.symbol:
            return PaperStartReport(
                signal.signal_id,"BLOQUEADO",
                ("ATIVO_DIVERGENTE",),None,None
            )
        proposal=ResearchIntent(
            signal_id=signal.signal_id, symbol=signal.symbol, side=signal.side,
            bid=Decimal(str(quote.bid)), ask=Decimal(str(quote.ask)),
            stop=Decimal(str(signal.stop))
        )
        budget=calculate_hypothetical_size(
            proposal,contract,limits,
            self._with_paper_exposure(external_hypothetical_portfolio)
        )
        if budget.status!="PESQUISA_APENAS" or budget.research_lots is None:
            return PaperStartReport(
                signal.signal_id,"BLOQUEADO",budget.block_codes,budget,None
            )
        identity=ResearchOrderIntent(
            signal.signal_id,VENUE,signal.symbol,signal.side,
            volume=str(budget.research_lots),
            stop=str(signal.stop),target=str(signal.target)
        )
        # Order of operations: reserve durable ID, then simulate position.
        # If the process crashes between both, restart quarantines the ID.
        new_id=self.journal.register(identity,at=quote.at)
        if not new_id:
            return PaperStartReport(
                signal.signal_id,"BLOQUEADO",
                ("ID_JA_RESERVADO_EM_DISCO",),budget,None
            )
        try:
            pos=self.book.open_hypothetical(signal,quote)
        except Exception:
            self.journal.transition(
                signal.signal_id,"BLOCKED_RESEARCH",at=quote.at,
                note="Ensaio recusado por preço/stop/alvo/tempo inválido"
            )
            raise
        self.journal.transition(
            signal.signal_id,"PAPER_POSITION_OPEN",at=quote.at,
            note="Abertura somente fictícia; nenhum envio ao MT5"
        )
        self._reserved_by_signal[signal.signal_id]=budget.illustrative_total
        return PaperStartReport(
            signal.signal_id,"PAPER_POSITION_OPEN",(),budget,pos
        )

    def observe_paper(self, signal_id: str, quote: PaperQuote
                      ) -> PaperPosition | PaperOutcome:
        """Observe a fictional stop/target with the appropriate quote side."""
        result=self.book.observe(signal_id,quote)
        if isinstance(result,PaperOutcome):
            destination={
                "ALVO_OBSERVADO":"SIMULATED_TARGET_OBSERVED",
                "STOP_OBSERVADO":"SIMULATED_STOP_OBSERVED",
                "COBERTURA_INSUFICIENTE":"SIMULATED_GAP_INCONCLUSIVE",
            }[result.outcome]
            self.journal.transition(
                signal_id,destination,at=quote.at,
                note="Desfecho de ensaio somente fictício (NÃO é fill MT5)"
            )
            self._reserved_by_signal.pop(signal_id,None)
        return result

    def prepare_after_restart(self, *, at: datetime) -> int:
        """Quarantine unfinished paper events from an earlier process.

        The in-memory position book cannot safely restore from SQLite
        because the quote trail / simulated position is not durable.
        Never infer a broker position from this research ledger.
        """
        return self.journal.quarantine_unresolved_after_restart(at=at)

    def open_paper_positions(self) -> int:
        return len(self.book.open_positions)


def fabricated_autonomous_cycle() -> dict[str, object]:
    """Deterministic fictional quote timeline; no MT5, no real money."""
    tick=datetime(2026,11,26,18,tzinfo=timezone.utc)
    contract=ResearchContract(
        symbol="FICTICIO",currency_for_tick_value="USD",
        tick_size=Decimal("0.01"),
        tick_value_loss_per_lot=Decimal("1"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("5.00"),
        volume_step=Decimal("0.01"),
    )
    limits=HypotheticalLimits(equity=Decimal("10000"),currency="USD")
    with TemporaryDirectory() as temp:
        path=Path(temp)/"paper_research.sqlite3"
        with ResearchIntentJournal(path) as ledger:
            lab=OfflineAutonomousPaperLab(ledger,max_quote_gap_seconds=2)
            buy=PaperIntent("FICTICIO-001","FICTICIO","buy",99,102)
            opened=lab.prepare_and_open_paper(
                buy,PaperQuote("FICTICIO",tick,100,100.2),
                contract,limits
            )
            if opened.status!="PAPER_POSITION_OPEN":
                raise AssertionError("Synthetic risk gate unexpectedly failed")
            # One intermediary tick, then simulated bid crosses the target.
            lab.observe_paper(
                buy.signal_id,
                PaperQuote("FICTICIO",tick+timedelta(seconds=1),100.8,101.0)
            )
            ended=lab.observe_paper(
                buy.signal_id,
                PaperQuote("FICTICIO",tick+timedelta(seconds=2),102.1,102.3)
            )
            duplicate=lab.prepare_and_open_paper(
                buy,PaperQuote("FICTICIO",tick+timedelta(seconds=3),100,100.2),
                contract,limits
            )
            if not isinstance(ended,PaperOutcome):
                raise AssertionError("Missing paper-only outcome")
            if duplicate.status!="BLOQUEADO" or duplicate.block_codes!=(
                "ID_JA_RESERVADO_EM_DISCO",
            ):
                raise AssertionError("Duplicate fictional event was not blocked")
            final_state=ledger.state(buy.signal_id)
        with ResearchIntentJournal(path) as restarted:
            quarantined=OfflineAutonomousPaperLab(
                restarted
            ).prepare_after_restart(at=tick+timedelta(seconds=4))
    return {
        "data":"INVENTADOS", "entry_price":opened.simulated_position.entry_price,
        "observed_exit_price":ended.observed_exit_price,
        "price_difference":ended.pnl_price_units,
        "outcome":ended.outcome,
        "estimated_risk_budget":str(opened.research_risk.available_budget),
        "estimated_research_lots":str(opened.research_risk.research_lots),
        "journal_terminal_state":final_state,
        "duplicate_stopped":True,
        "unresolved_after_restart":quarantined,
        "orders_sent":0,
    }


if __name__=="__main__":
    result=fabricated_autonomous_cycle()
    print("CICLO AUTONOMO FICTICIO — ABERTURA/ACOMPANHAMENTO/SAIDA")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("SEM MT5, SEM ORDENS, SEM RESULTADO FINANCEIRO VERIFICADO.")
