"""Read a native MT5 Tools/Symbols/Ticks tab-delimited export safely.

The export contains timestamps WITHOUT timezone and often quote updates where
only one of Bid or Ask is present. NEVER infer offset or absent quote sides.
This module deliberately does not access an account or send any order.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Iterator

from .ticks import aggregate_bidask_ticks
from .lifecycle import _aware

_COLUMNS = ("<DATE>", "<TIME>", "<BID>", "<ASK>", "<LAST>", "<VOLUME>", "<FLAGS>")


@dataclass(frozen=True)
class MT5ExportQuality:
    records: int
    complete_bid_ask: int
    bid_only: int
    ask_only: int
    neither: int
    first_server_time: str
    last_server_time: str
    gaps_over_300s: int
    max_gap_seconds: float
    source_timezone: str = "UNSPECIFIED_IN_EXPORT"


def _tick_rows(path: str | Path, max_rows: int) -> Iterator[tuple[int, datetime, float | None, float | None]]:
    if not 1 <= max_rows <= 5_000_000:
        raise ValueError("max_rows must be between 1 and 5000000")
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames is None or tuple(reader.fieldnames) != _COLUMNS:
            raise ValueError("Not the expected native MT5 tick export header")
        previous = None
        for n, row in enumerate(reader, start=1):
            if n > max_rows:
                raise ValueError("Input exceeds safe row maximum")
            try:
                stamp = datetime.strptime(
                    row["<DATE>"] + " " + row["<TIME>"],
                    "%Y.%m.%d %H:%M:%S.%f"
                )
                # Export is timezone-naive: keep it naive here until the
                # user supplies a broker-verified historical server offset.
                values = []
                for field in ("<BID>", "<ASK>"):
                    raw = row[field]
                    parsed = float(raw) if raw else None
                    if parsed is not None and (not isfinite(parsed) or parsed <= 0):
                        raise ValueError("Invalid quote price")
                    values.append(parsed)
                bid, ask = values
                if bid is not None and ask is not None and ask < bid:
                    raise ValueError("Ask below Bid in same quote record")
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"Invalid MT5 export row {n+1}: {exc}") from exc
            if previous is not None and stamp <= previous:
                raise ValueError(f"Out-of-order or repeated export timestamp at row {n+1}")
            previous = stamp
            yield n, stamp, bid, ask


def inspect_mt5_export(path: str | Path, max_rows: int = 2_000_000) -> MT5ExportQuality:
    """Inspect data quality without claiming to know the historical timezone."""
    total = complete = bidonly = askonly = neither = gaps = 0
    biggest = 0.0
    earliest = latest = previous = None
    for _, stamp, bid, ask in _tick_rows(path, max_rows):
        if earliest is None:
            earliest = stamp
        if previous is not None:
            delta = (stamp-previous).total_seconds()
            if delta > 300:
                gaps += 1
                biggest = max(biggest, delta)
        previous = latest = stamp
        total += 1
        if bid is not None and ask is not None:
            complete += 1
        elif bid is not None:
            bidonly += 1
        elif ask is not None:
            askonly += 1
        else:
            neither += 1
    if earliest is None:
        raise ValueError("Empty MT5 tick export")
    return MT5ExportQuality(total, complete, bidonly, askonly, neither,
                            earliest.isoformat(), latest.isoformat(), gaps, biggest)


def load_mt5_quote_export(
    path: str | Path, *, venue: str, symbol: str,
    verified_utc_offset_minutes: int | None,
    timeframe_seconds: int, as_of: datetime,
    max_rows: int = 2_000_000,
):
    """Load COMPLETE bid/ask records only, with an EXPLICIT verified offset.

    Does not fill missing bid or ask updates. It is deliberately conservative
    and unsuitable for final expectancy/fill modeling until verified against
    the original tick stream and venue contract conventions.
    """
    if verified_utc_offset_minutes is None or type(verified_utc_offset_minutes) is not int:
        raise ValueError("Broker's historical UTC offset must be explicitly verified")
    if not -720 <= verified_utc_offset_minutes <= 840:
        raise ValueError("UTC offset outside supported UTC-12 to UTC+14 range")
    _aware(as_of, "as_of")
    if not venue or not symbol:
        raise ValueError("Explicit platform-native venue and symbol required")
    tz = timezone(timedelta(minutes=verified_utc_offset_minutes))

    def usable():
        for _, stamp, bid, ask in _tick_rows(path, max_rows):
            if bid is None or ask is None:
                # An MT5 update-only row does not establish both quotes;
                # do not guess a missing side from a previous row.
                continue
            aware = stamp.replace(tzinfo=tz).astimezone(timezone.utc)
            time_msc = int(round(aware.timestamp() * 1000))
            yield {"time_msc": time_msc, "bid": bid, "ask": ask}

    return aggregate_bidask_ticks(
        usable(), venue=venue, symbol=symbol,
        source="MT5_EXPORT_BOTH_SIDES_ONLY_REQUIRES_COVERAGE_REVIEW",
        timeframe_seconds=timeframe_seconds, as_of=as_of,
        max_ticks=max_rows
    )
