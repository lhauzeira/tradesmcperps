"""Conservative, read-only OHLC audit of a *published* trading signal.

This is NOT a backtest, broker fill simulator, profit report, or live executor.
OHLC bars do not reveal the order of intrabar price touches. No result here
may be presented as a verified fill, payout, or realized gain/loss.

Rules:
* Compare ONLY a feed explicitly identified as the same venue and instrument.
* Observe ONLY fully closed bars whose OPEN is strictly after publication.
* Never assume intrabar sequencing: ambiguous bars stay ambiguous.
* Signal expires after a configurable number of fully observable bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include timezone information")


@dataclass(frozen=True)
class ObservedBar:
    opened_at: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self):
        _aware(self.opened_at, "opened_at")
        _aware(self.closed_at, "closed_at")
        if not self.opened_at < self.closed_at:
            raise ValueError("Bar must have positive duration")
        values = (self.open, self.high, self.low, self.close)
        if not all(isfinite(x) and x > 0 for x in values):
            raise ValueError("OHLC must be positive and finite")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Inconsistent OHLC")


@dataclass(frozen=True)
class PublishedSignal:
    signal_id: str
    venue: str
    symbol: str
    published_at: datetime
    side: str
    entry: float
    stop: float
    target: float

    def __post_init__(self):
        _aware(self.published_at, "published_at")
        if not all((self.signal_id, self.venue, self.symbol)):
            raise ValueError("Signal identity, venue and symbol are required")
        if self.side not in ("buy", "sell"):
            raise ValueError("Signal side must be buy or sell")
        values = (self.entry, self.stop, self.target)
        if not all(isfinite(x) and x > 0 for x in values):
            raise ValueError("Price levels must be positive and finite")
        if self.side == "buy" and not self.stop < self.entry < self.target:
            raise ValueError("Invalid long stop/entry/target arrangement")
        if self.side == "sell" and not self.target < self.entry < self.stop:
            raise ValueError("Invalid short stop/entry/target arrangement")


@dataclass(frozen=True)
class Observation:
    signal_id: str
    status: str
    bars_examined: int
    entry_touch_at: datetime | None = None
    boundary_touch_at: datetime | None = None
    note: str = "Price-level observation only; no broker fill evidence."


def observe(
    signal: PublishedSignal,
    bars: Iterable[ObservedBar],
    *,
    feed_venue: str,
    feed_symbol: str,
    as_of: datetime,
    max_bars: int = 48,
) -> Observation:
    """Audit a *single* fixed-level signal without assuming an execution.

    Each bar whose open is <= publication time is excluded in full, even when
    its close is later. Unclosed future bars are excluded using as_of.
    OHLC alone is insufficient to establish whether a limit order was filled.
    """
    _aware(as_of, "as_of")
    if as_of < signal.published_at:
        raise ValueError("as_of precedes signal publication")
    if feed_venue != signal.venue or feed_symbol != signal.symbol:
        raise ValueError("Different venue or instrument: refuse cross-market outcome")
    if not 1 <= max_bars <= 10000:
        raise ValueError("max_bars out of range")

    all_bars = list(bars)
    for previous, current in zip(all_bars, all_bars[1:]):
        if current.opened_at < previous.closed_at:
            raise ValueError("Bars overlap or are not chronological")

    usable = [
        b for b in all_bars
        if b.opened_at > signal.published_at and b.closed_at <= as_of
    ][:max_bars]

    if not usable:
        return Observation(signal.signal_id, "NO_POST_PUBLICATION_DATA", 0)

    entry_at = None
    for i, bar in enumerate(usable, start=1):
        entry_touched = bar.low <= signal.entry <= bar.high
        stop_touched = bar.low <= signal.stop <= bar.high
        target_touched = bar.low <= signal.target <= bar.high

        if entry_at is None:
            if not entry_touched:
                continue
            entry_at = bar.closed_at
            # The same OHLC interval may touch levels in any order.
            if stop_touched or target_touched:
                return Observation(
                    signal.signal_id, "AMBIGUOUS_ENTRY_BAR", i,
                    entry_touch_at=entry_at, boundary_touch_at=bar.closed_at,
                    note="Entry and exit boundary in the same bar; intrabar order unknown.")
            continue

        # If a later bar opens beyond either boundary, there is no safe
        # price-level exit estimate from OHLC alone.
        gap_beyond = (
            bar.open < signal.stop or bar.open > signal.target
            if signal.side == "buy"
            else bar.open > signal.stop or bar.open < signal.target
        )
        if gap_beyond:
            return Observation(
                signal.signal_id, "GAP_EXIT_UNPRICED", i,
                entry_touch_at=entry_at, boundary_touch_at=bar.closed_at,
                note="Bar opened beyond the stop or target; execution price cannot be inferred.")
        if stop_touched and target_touched:
            return Observation(
                signal.signal_id, "AMBIGUOUS_EXIT_BAR", i,
                entry_touch_at=entry_at, boundary_touch_at=bar.closed_at,
                note="Stop and target touched in the same bar; intrabar order unknown.")
        if stop_touched:
            return Observation(
                signal.signal_id, "STOP_LEVEL_TOUCHED", i,
                entry_touch_at=entry_at, boundary_touch_at=bar.closed_at)
        if target_touched:
            return Observation(
                signal.signal_id, "TARGET_LEVEL_TOUCHED", i,
                entry_touch_at=entry_at, boundary_touch_at=bar.closed_at)

    if len(usable) == max_bars:
        return Observation(
            signal.signal_id,
            "UNRESOLVED_AFTER_ENTRY" if entry_at else "EXPIRED_NO_ENTRY",
            len(usable), entry_touch_at=entry_at,
            note="Observation horizon elapsed; no executed trade confirmed.")

    return Observation(
        signal.signal_id,
        "ENTRY_LEVEL_TOUCHED_AWAITING_OUTCOME" if entry_at else "AWAITING_ENTRY_LEVEL",
        len(usable), entry_touch_at=entry_at)
