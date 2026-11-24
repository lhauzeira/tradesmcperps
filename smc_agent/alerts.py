"""Research-only signal event records and Telegram message *previews*.

NO network connection, Telegram API call, or trading execution.
These records are NOT confirmations of market profitability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from math import isclose, isfinite
import re

from .engine import Signal


_ALLOWED_TIMES = {"M1", "M2", "M5", "M15", "H1", "H4", "D1"}
_SYMBOL = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


@dataclass(frozen=True)
class SignalRecord:
    """A signal generated at the close of an explicitly named bar."""
    event_id: str
    symbol: str
    timeframe: str
    candle_closed_at: datetime
    side: str
    entry: float
    stop: float
    target: float
    rr: float
    reason: str
    source: str = "smc-research"

    def __post_init__(self):
        if self.candle_closed_at.tzinfo is None or self.candle_closed_at.utcoffset() is None:
            raise ValueError("Signal timestamp must be timezone-aware")
        if not _SYMBOL.fullmatch(self.symbol) or self.timeframe not in _ALLOWED_TIMES:
            raise ValueError("Invalid market symbol or timeframe")
        if self.side not in ("buy", "sell"):
            raise ValueError("Invalid trade side")
        if not all(isfinite(x) and x > 0 for x in (self.entry, self.stop, self.target, self.rr)):
            raise ValueError("Prices and risk/reward must be positive finite numbers")
        if self.side == "buy" and not (self.stop < self.entry < self.target):
            raise ValueError("Buy stop and target must bracket entry correctly")
        if self.side == "sell" and not (self.target < self.entry < self.stop):
            raise ValueError("Sell stop and target must bracket entry correctly")
        actual_rr = abs(self.target - self.entry) / abs(self.entry - self.stop)
        if not isclose(actual_rr, self.rr, rel_tol=1e-5):
            raise ValueError("Risk/reward mismatch")
        if not self.event_id or not self.source or not self.reason:
            raise ValueError("Event must have id, source and explanation")


def from_engine(signal: Signal, *, symbol: str, timeframe: str,
                candle_closed_at: datetime, source: str = "smc-research") -> SignalRecord:
    """Create stable event ID: same market/bar/setup produces the same ID.

    The caller MUST pass the actual close timestamp, not an open-bar time.
    """
    if candle_closed_at.tzinfo is None or candle_closed_at.utcoffset() is None:
        raise ValueError("Candle close time must have timezone")
    when = candle_closed_at.astimezone(timezone.utc).isoformat()
    identity = "|".join((source, symbol, timeframe, when, signal.side,
                         str(signal.ob.candle_index), str(signal.ob.bos_index)))
    event_id = sha256(identity.encode("utf-8")).hexdigest()[:20]
    return SignalRecord(
        event_id=event_id, symbol=symbol, timeframe=timeframe,
        candle_closed_at=candle_closed_at.astimezone(timezone.utc),
        side=signal.side, entry=signal.entry, stop=signal.stop,
        target=signal.target, rr=signal.rr, reason=signal.reason, source=source,
    )


def telegram_preview(record: SignalRecord) -> str:
    """HTML-escaped text preview ONLY. No Telegram connection is made."""
    direction = "COMPRA" if record.side == "buy" else "VENDA"
    when = record.candle_closed_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "<b>SIMULACAO DE ALERTA — NAO OPERAR</b>",
        f"<b>{escape(record.symbol)} ({escape(record.timeframe)})</b> — {direction}",
        f"Candle fechado: {when}",
        f"Entrada teorica: {record.entry:.5f}",
        f"Stop: {record.stop:.5f}",
        f"Alvo: {record.target:.5f}",
        f"Risco/retorno bruto: {record.rr:.2f}R",
        f"Motivo: {escape(record.reason)}",
        f"ID: {record.event_id}",
        "<i>Pesquisa: sem ordem, sem custos calculados, sem validacao de lucratividade.</i>"
    ]
    return "\n".join(lines)


class AlertBuffer:
    """De-duplicates within process memory. A restart resets this buffer."""
    def __init__(self):
        self._seen = set()

    def enqueue(self, record: SignalRecord) -> bool:
        if record.event_id in self._seen:
            return False
        self._seen.add(record.event_id)
        return True
