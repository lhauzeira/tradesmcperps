"""Classify five-timeframe context around a *research-only* SMC signal.

This labels evidence in event logs for future A/B testing. It does NOT
filter, rank expected profitability, size positions or authorize orders.
Unknown timeframe data is never reinterpreted as a neutral market.
"""
from __future__ import annotations

from dataclasses import dataclass

from .multi_timeframe import MultiTimeframeContext


@dataclass(frozen=True)
class MTFSignalContext:
    signal_side: str
    matched: tuple[str, ...]
    opposed: tuple[str, ...]
    neutral: tuple[str, ...]
    unavailable: tuple[str, ...]
    higher_tf: str
    intermediates: str
    label: str
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.signal_side not in ("buy", "sell"):
            raise ValueError("Invalid signal side")
        if self.can_submit_orders:
            raise ValueError("MTF context never authorizes orders")

    def to_log(self) -> dict[str, object]:
        return {
            "label": self.label,
            "h4_context": self.higher_tf,
            "m30_m15_context": self.intermediates,
            "matched": list(self.matched),
            "opposed": list(self.opposed),
            "neutral": list(self.neutral),
            "unavailable": list(self.unavailable),
            "orders_authorized": False,
        }


def classify_signal_context(
    side: str, context: MultiTimeframeContext
) -> MTFSignalContext:
    """Describe observed confluences without asserting a trading edge."""
    if side not in ("buy", "sell"):
        raise ValueError("Expected buy or sell signal side")
    if not isinstance(context, MultiTimeframeContext):
        raise TypeError("Five-timeframe context required")
    wanted = "ALTA" if side == "buy" else "BAIXA"
    other = "BAIXA" if side == "buy" else "ALTA"
    matched = tuple(f.timeframe for f in context.frames if f.bias == wanted)
    opposed = tuple(f.timeframe for f in context.frames if f.bias == other)
    neutral = tuple(f.timeframe for f in context.frames if f.bias == "NEUTRO")
    missing = tuple(f.timeframe for f in context.frames if f.state != "OK")
    by_tf = {f.timeframe: f for f in context.frames}
    h4 = by_tf["H4"]
    if h4.state != "OK":
        h4_label = "H4_INDISPONIVEL"
    elif h4.bias == wanted:
        h4_label = "H4_A_FAVOR"
    elif h4.bias == other:
        h4_label = "H4_CONTRA"
    else:
        h4_label = "H4_NEUTRO"

    inter = (by_tf["M30"], by_tf["M15"])
    yes = sum(f.bias == wanted for f in inter)
    no = sum(f.bias == other for f in inter)
    if any(f.state != "OK" for f in inter):
        inter_label = "INTERMEDIARIOS_INCOMPLETOS"
    elif yes == 2:
        inter_label = "AMBOS_A_FAVOR"
    elif no == 2:
        inter_label = "AMBOS_CONTRA"
    elif yes > no:
        inter_label = "MAIS_A_FAVOR"
    elif no > yes:
        inter_label = "MAIS_CONTRA"
    else:
        inter_label = "MISTO_OU_NEUTRO"

    # Useful cohort labels for later out-of-sample analysis, NOT a gate.
    if h4_label == "H4_A_FAVOR" and yes >= 1 and len(missing) == 0:
        label = "CONFLUENCIA_COMPLETA_OBSERVADA"
    elif h4_label == "H4_CONTRA":
        label = "CONTRA_FLUXO_H4"
    elif h4_label == "H4_INDISPONIVEL" or len(missing):
        label = "COBERTURA_INSUFICIENTE"
    else:
        label = "CONFLUENCIA_NAO_CONFIRMADA"

    return MTFSignalContext(
        signal_side=side,
        matched=matched,
        opposed=opposed,
        neutral=neutral,
        unavailable=missing,
        higher_tf=h4_label,
        intermediates=inter_label,
        label=label,
    )
