"""Strict, venue-aware bid/ask OHLC import for offline research only.

No exchange connectivity, brokerage authentication or execution.
Sample CSV in this repository is synthetic. Real feeds must carry their own
verified provenance and native quote semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
from math import isfinite
from pathlib import Path

from .lifecycle import _aware, PublishedSignal, Observation


@dataclass(frozen=True)
class QuoteBar:
    opened_at: datetime
    closed_at: datetime
    bid_open: float
    bid_high: float
    bid_low: float
    bid_close: float
    ask_open: float
    ask_high: float
    ask_low: float
    ask_close: float

    def __post_init__(self):
        _aware(self.opened_at, "opened_at")
        _aware(self.closed_at, "closed_at")
        if self.opened_at >= self.closed_at:
            raise ValueError("Quote bar has invalid open and close times")
        b = (self.bid_open, self.bid_high, self.bid_low, self.bid_close)
        a = (self.ask_open, self.ask_high, self.ask_low, self.ask_close)
        if not all(isfinite(v) and v > 0 for v in b + a):
            raise ValueError("Quote OHLC must be finite, strictly positive numbers")
        if self.bid_low > min(self.bid_open, self.bid_close) or self.bid_high < max(self.bid_open, self.bid_close):
            raise ValueError("Invalid bid OHLC")
        if self.ask_low > min(self.ask_open, self.ask_close) or self.ask_high < max(self.ask_open, self.ask_close):
            raise ValueError("Invalid ask OHLC")
        # With synchronized time intervals, ask must not be below bid
        # at the open/close or when comparing extrema.
        if any(x < y for x, y in (
            (self.ask_open, self.bid_open),
            (self.ask_close, self.bid_close),
            (self.ask_high, self.bid_high),
            (self.ask_low, self.bid_low),
        )):
            raise ValueError("Ask below bid; data may be corrupt or unsynchronized")

    @property
    def open_spread(self) -> float:
        return self.ask_open - self.bid_open

    @property
    def close_spread(self) -> float:
        return self.ask_close - self.bid_close


@dataclass(frozen=True)
class QuoteHistory:
    venue: str
    symbol: str
    origin: str
    bars: tuple[QuoteBar, ...]

    def __post_init__(self):
        if not self.venue or not self.symbol or not self.origin:
            raise ValueError("Venue, instrument and provenance required")
        if not self.bars:
            raise ValueError("Empty bid/ask history")
        for prev, curr in zip(self.bars, self.bars[1:]):
            if curr.opened_at < prev.closed_at:
                raise ValueError("Duplicate, overlapping or unsorted quote bars")


_COLUMNS = (
    "venue", "symbol", "origin", "closed",
    "opened_at", "closed_at",
    "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close",
)
_PRICE_COLS = _COLUMNS[6:]


def _datetime(value: str, label: str) -> datetime:
    if not value:
        raise ValueError(f"Missing {label}")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    _aware(parsed, label)
    return parsed.astimezone(timezone.utc)


def load_quote_csv(path: str | Path, *, max_rows: int = 200000) -> QuoteHistory:
    """Explicit schema; never fabricate Ask OHLC from Bid OHLC or fixed spread.

    Require each row to be marked final/closed. Reject multiple venues or
    instruments in one file. Noncontiguous trading sessions are supported.
    """
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    bars = []
    meta = None
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(reader.fieldnames) != set(_COLUMNS):
            raise ValueError("CSV must contain exactly the declared bid/ask schema")
        for line, row in enumerate(reader, start=2):
            if len(bars) >= max_rows:
                raise ValueError("CSV exceeds configured row limit")
            try:
                if row["closed"].strip().lower() not in ("true", "1"):
                    raise ValueError("Unclosed bars are not accepted")
                current_meta = (row["venue"].strip(), row["symbol"].strip(), row["origin"].strip())
                if not all(current_meta):
                    raise ValueError("Missing venue, symbol or origin")
                if meta is None:
                    meta = current_meta
                elif current_meta != meta:
                    raise ValueError("Mixed venue, instrument or origin")
                values = {key: float(row[key]) for key in _PRICE_COLS}
                bars.append(QuoteBar(
                    opened_at=_datetime(row["opened_at"], "opened_at"),
                    closed_at=_datetime(row["closed_at"], "closed_at"),
                    **values,
                ))
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Malformed quote CSV at row {line}: {exc}") from exc
    if meta is None:
        raise ValueError("Quote history is empty")
    return QuoteHistory(*meta, tuple(bars))


def observe_quotes(
    signal: PublishedSignal, history: QuoteHistory, *,
    as_of: datetime, max_bars: int = 48, quote_policy: str,
    max_open_spread_pct: float | None = None,
) -> Observation:
    """Conservative price-touch observation with bid/ask *proxy* semantics.

    quote_policy='buy_ask_sell_bid': long entry uses ASK, long exits BID;
    short entry BID, short exits ASK. No order style/fills are implied.
    Other signal quote conventions are refused until separately specified.
    """
    _aware(as_of, "as_of")
    if as_of < signal.published_at:
        raise ValueError("Observation cutoff precedes published signal")
    if (signal.venue, signal.symbol) != (history.venue, history.symbol):
        raise ValueError("Native venue/instrument mismatch; no offset translation")
    if quote_policy != "buy_ask_sell_bid":
        raise ValueError("Explicit supported quote convention required")
    if not 1 <= max_bars <= 10000:
        raise ValueError("Invalid number of observation bars")
    if max_open_spread_pct is not None and (
        not isfinite(max_open_spread_pct) or not 0 < max_open_spread_pct <= 10
    ):
        raise ValueError("Spread threshold must be > 0 and <= 10 percent")

    usable = [
        b for b in history.bars
        if b.opened_at > signal.published_at and b.closed_at <= as_of
    ][:max_bars]
    if not usable:
        return Observation(signal.signal_id, "NO_POST_PUBLICATION_DATA", 0)

    entry_at = None
    for i, b in enumerate(usable, start=1):
        quote_mid = (b.ask_open + b.bid_open) / 2
        spread_pct = b.open_spread / quote_mid * 100
        if max_open_spread_pct is not None and spread_pct > max_open_spread_pct:
            return Observation(
                signal.signal_id, "SPREAD_THRESHOLD_EXCEEDED", i,
                entry_touch_at=entry_at, boundary_touch_at=b.closed_at,
                note="Feed spread exceeded caller's limit; no trade performance assumed.")
        if signal.side == "buy":
            entry_low, entry_high = b.ask_low, b.ask_high
            exit_low, exit_high, exit_open = b.bid_low, b.bid_high, b.bid_open
            gap = exit_open < signal.stop or exit_open > signal.target
        else:
            entry_low, entry_high = b.bid_low, b.bid_high
            exit_low, exit_high, exit_open = b.ask_low, b.ask_high, b.ask_open
            gap = exit_open > signal.stop or exit_open < signal.target

        touched_entry = entry_low <= signal.entry <= entry_high
        touched_stop = exit_low <= signal.stop <= exit_high
        touched_target = exit_low <= signal.target <= exit_high
        if entry_at is None:
            if not touched_entry:
                continue
            entry_at = b.closed_at
            if touched_stop or touched_target:
                return Observation(
                    signal.signal_id, "AMBIGUOUS_ENTRY_BAR", i,
                    entry_touch_at=entry_at, boundary_touch_at=b.closed_at,
                    note="Entry quote and exit quote touched within one OHLC bar; sequence unknown.")
            continue

        if gap:
            return Observation(
                signal.signal_id, "GAP_EXIT_UNPRICED", i,
                entry_touch_at=entry_at, boundary_touch_at=b.closed_at,
                note="Exit quote opened beyond an exit boundary; fill price unknown.")
        if touched_stop and touched_target:
            return Observation(
                signal.signal_id, "AMBIGUOUS_EXIT_BAR", i,
                entry_touch_at=entry_at, boundary_touch_at=b.closed_at,
                note="Both exit boundaries observed in the same OHLC bar.")
        if touched_stop:
            return Observation(signal.signal_id, "STOP_LEVEL_TOUCHED", i,
                               entry_touch_at=entry_at, boundary_touch_at=b.closed_at)
        if touched_target:
            return Observation(signal.signal_id, "TARGET_LEVEL_TOUCHED", i,
                               entry_touch_at=entry_at, boundary_touch_at=b.closed_at)

    if len(usable) == max_bars:
        return Observation(
            signal.signal_id,
            "UNRESOLVED_AFTER_ENTRY" if entry_at else "EXPIRED_NO_ENTRY",
            len(usable), entry_touch_at=entry_at,
            note="Observation horizon exhausted; quote levels only.")
    return Observation(
        signal.signal_id,
        "ENTRY_LEVEL_TOUCHED_AWAITING_OUTCOME" if entry_at else "AWAITING_ENTRY_LEVEL",
        len(usable), entry_touch_at=entry_at,
        note="Native bid/ask quote levels, not broker executions.")
