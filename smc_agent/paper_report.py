"""Conservative batch summary of hypothetical PAPER-only outcomes.

Never report a real-world win rate, profit factor or realized P&L from
partial/ambiguous outcome data. A target-level paper model is NOT a broker
execution. User's private Telegram conversations are never processed here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .paper import PaperResult


MODEL_RESOLVED = frozenset(("PAPER_STOP_MODEL", "PAPER_TARGET_MODEL"))
ALL_PAPER_STATUSES = frozenset((
    "NO_POST_PUBLICATION_DATA", "NO_ENTRY_STALE_QUOTES",
    "CANDLE_DURATION_UNVERIFIED", "QUOTE_GAP_UNRESOLVED",
    "SESSION_UNVERIFIED", "NO_ENTRY_SESSION_CLOSED",
    "SESSION_CLOSED_AFTER_PAPER_ENTRY", "NO_ENTRY_WIDE_SPREAD",
    "SPREAD_VETO_AFTER_PAPER_ENTRY", "NO_ENTRY_PRICE_DRIFT",
    "NO_ENTRY_INVALID_QUOTE", "NO_ENTRY_EXIT_QUOTE_OUTSIDE_LEVELS",
    "NO_TRADE_RISK_CAP", "NO_TRADE_MIN_LOT_RISK",
    "GAP_EXIT_UNPRICED", "AMBIGUOUS_INTRA_BAR", "PAPER_STOP_MODEL",
    "PAPER_TARGET_MODEL", "PAPER_OPEN_UNRESOLVED",
))


@dataclass(frozen=True)
class PaperBatchSummary:
    dataset_label: str
    scenarios_submitted: int
    modeled_target_touches: int
    modeled_stop_touches: int
    unresolved_or_blocked: int
    estimated_net_resolved_subset_only_usd: Decimal
    statuses: tuple[tuple[str, int], ...]
    # Deliberately unavailable until independent broker reconciliation:
    verified_realized_pnl_usd: None = None
    verified_win_rate: None = None
    verified_profit_factor: None = None
    completed_live_orders: int = 0

    @property
    def modeled_resolved_count(self) -> int:
        return self.modeled_target_touches + self.modeled_stop_touches


def summarize_paper_results(
    results: Iterable[PaperResult], *, dataset_label: str
) -> PaperBatchSummary:
    """Audit all scenarios, including those without a paper result.

    Reject duplicate signal identifiers instead of inflating modeled results.
    Return only a *partial sum* for modeled-stop/target outcomes, not an
    account P&L, and explicitly leave verified statistics unavailable.
    """
    if not dataset_label or not dataset_label.strip():
        raise ValueError("Explicit dataset label is required")
    seen: set[str] = set()
    counts: Counter = Counter()
    net = Decimal("0")
    total = 0
    for result in results:
        if result.signal_id in seen:
            raise ValueError("Duplicate signal ID: refuse double-counting")
        if not result.signal_id:
            raise ValueError("Missing signal ID")
        if result.status not in ALL_PAPER_STATUSES:
            raise ValueError("Unrecognized paper status")
        seen.add(result.signal_id)
        total += 1
        counts[result.status] += 1
        if result.orders_sent != 0 or result.broker_fills_verified:
            raise ValueError("This report accepts hypothetical paper records only")
        fields = (
            result.paper_entry_price, result.paper_exit_price,
            result.paper_lots, result.modeled_gross_usd,
            result.modeled_net_usd, result.modeled_fees_usd
        )
        if result.status in MODEL_RESOLVED:
            if any(value is None for value in fields):
                raise ValueError("Resolved paper result is missing required values")
            if any(not value.is_finite() for value in fields):
                raise ValueError("Invalid nonfinite modeled money")
            if result.paper_lots <= 0 or result.modeled_fees_usd < 0:
                raise ValueError("Impossible modeled volume/fee")
            if result.modeled_gross_usd - result.modeled_fees_usd != result.modeled_net_usd:
                raise ValueError("Inconsistent modeled net and fees")
            net += result.modeled_net_usd
        elif any(value is not None for value in (
            result.paper_exit_price, result.modeled_gross_usd,
            result.modeled_net_usd, result.modeled_fees_usd
        )):
            raise ValueError("Inconclusive scenario must not contain modeled P&L")

    count_target = counts["PAPER_TARGET_MODEL"]
    count_stop = counts["PAPER_STOP_MODEL"]
    return PaperBatchSummary(
        dataset_label=dataset_label,
        scenarios_submitted=total,
        modeled_target_touches=count_target,
        modeled_stop_touches=count_stop,
        unresolved_or_blocked=total-count_target-count_stop,
        estimated_net_resolved_subset_only_usd=net,
        statuses=tuple(sorted(counts.items()))
    )
