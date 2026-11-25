"""Conservative reconstruction of closed bid/ask OHLC from native quote ticks.

Importing THIS module does not connect to a broker. This accepts an already
obtained, complete native tick batch. Missing history is never filled with
synthetic prices. Quote intervals follow UTC wall-clock alignment; broker
bar-session alignment may be different and requires independent validation.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from math import isfinite
from numbers import Integral
from typing import Iterable, Mapping

from .lifecycle import _aware
from .quotes import QuoteHistory, QuoteBar

_SUPPORTED_SECONDS = {60, 120, 300, 900, 3600, 14400}


def aggregate_bidask_ticks(
    ticks: Iterable[Mapping], *, venue: str, symbol: str,
    source: str, timeframe_seconds: int, as_of: datetime,
    max_ticks: int = 500000,
) -> QuoteHistory:
    """Build quote OHLC from tick snapshots, NOT a historical fill simulator.

    Every tick must contain synchronized time_msc, bid, ask fields; unchanged
    quotes should be carried in by the upstream native provider. Reject stale,
    crossed or invalid quote snapshots; do not fabricate missing timestamps.
    """
    _aware(as_of, "as_of")
    if timeframe_seconds not in _SUPPORTED_SECONDS:
        raise ValueError("Unsupported quote interval")
    if not venue or not symbol or not source:
        raise ValueError("Missing broker/market provenance")
    if max_ticks <= 0:
        raise ValueError("max_ticks must be positive")

    groups = {}
    last_ms = None
    count = 0

    for tick in ticks:
        count += 1
        if count > max_ticks:
            raise ValueError("Tick history exceeded configured maximum")
        try:
            raw_ms = tick["time_msc"]
            # Python's bool is a subtype of int; exclude it.
            if isinstance(raw_ms, bool) or not isinstance(raw_ms, Integral):
                raise ValueError("time_msc must be integer UTC epoch milliseconds")
            millis = int(raw_ms)
            bid, ask = float(tick["bid"]), float(tick["ask"])
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError("Tick must contain valid time_msc/bid/ask fields") from error
        if millis < 0 or not (isfinite(bid) and isfinite(ask) and 0 < bid <= ask):
            raise ValueError("Invalid or crossed quote tick")
        if last_ms is not None and millis < last_ms:
            raise ValueError("Tick snapshots are not sorted chronologically")
        last_ms = millis
        try:
            when = datetime.fromtimestamp(millis/1000, tz=timezone.utc)
        except (ValueError, OverflowError, OSError) as error:
            raise ValueError("Tick timestamp out of range") from error
        if when > as_of:
            raise ValueError("Future tick relative to specified observation cutoff")
        bucket = (millis // (timeframe_seconds * 1000)) * timeframe_seconds
        begin = datetime.fromtimestamp(bucket, tz=timezone.utc)
        finish = begin + timedelta(seconds=timeframe_seconds)

        if bucket not in groups:
            groups[bucket] = [begin, finish, bid, bid, bid, bid, ask, ask, ask, ask]
            continue
        row = groups[bucket]
        row[3] = max(row[3], bid)
        row[4] = min(row[4], bid)
        row[5] = bid
        row[7] = max(row[7], ask)
        row[8] = min(row[8], ask)
        row[9] = ask

    bars = []
    for _, items in sorted(groups.items()):
        if items[1] <= as_of:
            bars.append(QuoteBar(*items))
    if not bars:
        raise ValueError("No fully closed quote interval available")
    return QuoteHistory(venue, symbol, source, tuple(bars))
