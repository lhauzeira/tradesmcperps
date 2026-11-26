"""Fully synthetic order lifecycle rehearsal — NEVER brokers/MT5.

This module has no MT5 import or order-send capability. It tests *decision
state* for hypothetical open/stop/target, not actual fills. Quotes must be
supplied externally; the sample CLI creates fictional prices. A gap in the
sampled quote sequence makes an outcome inconclusive, never a fabricated win.

PnL is in PRICE UNITS only, not dollars, BRL, lots or account returns.
No real volume, contract economics, margin or slippage is verified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite


def _num(value: object, name: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value <= 0):
        raise ValueError(f"{name} must be finite positive price")
    return float(value)


def _time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Quote time must include UTC offset")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class PaperIntent:
    signal_id: str
    symbol: str
    side: str
    stop: float
    target: float

    def __post_init__(self) -> None:
        if (not self.signal_id or not self.symbol
                or self.side not in ("buy", "sell")):
            raise ValueError("Invalid paper intent")
        _num(self.stop, "stop")
        _num(self.target, "target")
        if self.stop == self.target:
            raise ValueError("Stop and target cannot be equal")


@dataclass(frozen=True)
class PaperQuote:
    symbol: str
    at: datetime
    bid: float
    ask: float

    def __post_init__(self):
        if not self.symbol:
            raise ValueError("Symbol required")
        _time(self.at)
        _num(self.bid, "bid")
        _num(self.ask, "ask")
        if self.ask < self.bid:
            raise ValueError("Crossed bid/ask quote")


@dataclass(frozen=True)
class PaperPosition:
    intent: PaperIntent
    opened_at: datetime
    entry_price: float
    last_seen: datetime


@dataclass(frozen=True)
class PaperOutcome:
    intent: PaperIntent
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    observed_exit_price: float | None
    pnl_price_units: float | None
    outcome: str

    def __post_init__(self):
        if self.outcome not in (
                "ALVO_OBSERVADO", "STOP_OBSERVADO", "COBERTURA_INSUFICIENTE"):
            raise ValueError("Invalid synthetic outcome")


class SyntheticPaperBook:
    """In-memory synthetic replay. Never called to send a broker order."""

    def __init__(self, *, max_quote_gap_seconds: float = 2.0):
        if (isinstance(max_quote_gap_seconds, bool)
                or not isinstance(max_quote_gap_seconds, (int, float))
                or not isfinite(max_quote_gap_seconds)
                or max_quote_gap_seconds <= 0):
            raise ValueError("Invalid synthetic quote gap")
        self.max_gap = float(max_quote_gap_seconds)
        self.open_positions: dict[str, PaperPosition] = {}
        self.closed_positions: dict[str, PaperOutcome] = {}

    def open_hypothetical(self, intent: PaperIntent, quote: PaperQuote) -> PaperPosition:
        if intent.signal_id in self.open_positions or intent.signal_id in self.closed_positions:
            raise ValueError("Duplicate synthetic signal ID")
        if intent.symbol != quote.symbol:
            raise ValueError("Wrong asset for paper entry")
        # A long pays the ask and exits on bid. A short receives the bid
        # and exits on ask. This avoids mid-price instant paper profits.
        price = quote.ask if intent.side == "buy" else quote.bid
        if ((intent.side == "buy" and not intent.stop < price < intent.target)
                or (intent.side == "sell" and not intent.target < price < intent.stop)):
            raise ValueError("Stop / target not correctly placed around bid/ask fill")
        stamp = _time(quote.at)
        position = PaperPosition(intent, stamp, price, stamp)
        self.open_positions[intent.signal_id] = position
        return position

    def observe(self, signal_id: str, quote: PaperQuote) -> PaperPosition | PaperOutcome:
        if signal_id in self.closed_positions:
            return self.closed_positions[signal_id]
        position = self.open_positions.get(signal_id)
        if position is None:
            raise KeyError("Unknown synthetic signal ID")
        if quote.symbol != position.intent.symbol:
            raise ValueError("Wrong asset for synthetic exit")

        stamp = _time(quote.at)
        if stamp <= position.last_seen:
            raise ValueError("Non-chronological synthetic quotes")
        delta = (stamp - position.last_seen).total_seconds()
        if delta > self.max_gap:
            return self._close(position, stamp, None, "COBERTURA_INSUFICIENTE")

        intent = position.intent
        exit_side_price = quote.bid if intent.side == "buy" else quote.ask
        if intent.side == "buy":
            stop_hit, target_hit = exit_side_price <= intent.stop, exit_side_price >= intent.target
        else:
            stop_hit, target_hit = exit_side_price >= intent.stop, exit_side_price <= intent.target
        if stop_hit or target_hit:
            status = "STOP_OBSERVADO" if stop_hit else "ALVO_OBSERVADO"
            return self._close(position, stamp, exit_side_price, status)

        new_state = PaperPosition(intent, position.opened_at, position.entry_price, stamp)
        self.open_positions[signal_id] = new_state
        return new_state

    def _close(self, pos: PaperPosition, stamp: datetime,
               exit_price: float | None, status: str) -> PaperOutcome:
        pnl = None if exit_price is None else (
            (exit_price - pos.entry_price) if pos.intent.side == "buy"
            else (pos.entry_price - exit_price)
        )
        report = PaperOutcome(pos.intent, pos.opened_at, stamp, pos.entry_price,
                              exit_price, pnl, status)
        del self.open_positions[pos.intent.signal_id]
        self.closed_positions[pos.intent.signal_id] = report
        return report


def synthetic_demo() -> str:
    """All prices intentionally invented. No MT5 connection or real orders."""
    t = datetime(2026, 1, 5, 14, tzinfo=timezone.utc)
    book = SyntheticPaperBook(max_quote_gap_seconds=3.0)
    intent = PaperIntent("FICTICIO-1", "EXEMPLO", "buy", stop=99.0, target=102.0)
    opened = book.open_hypothetical(
        intent, PaperQuote("EXEMPLO", t, bid=100.0, ask=100.2)
    )
    closed = book.observe(
        intent.signal_id,
        PaperQuote("EXEMPLO", t+timedelta(seconds=1), bid=102.1, ask=102.3)
    )
    return (
        "SIMULACAO COMPLETAMENTE FICTICIA — NAO ACESSA MT5, SEM ORDENS\n"
        f"Abertura hipotetica BUY no Ask: {opened.entry_price:.2f}\n"
        f"Saida teorica no Bid: {closed.observed_exit_price:.2f}\n"
        f"Resultado em unidades de PRECO (nao USD): {closed.pnl_price_units:.2f}\n"
        f"Estado: {closed.outcome}\n"
        "Zero ordens enviadas. Nao comprova executabilidade ou lucro."
    )


if __name__ == "__main__":
    print(synthetic_demo())
