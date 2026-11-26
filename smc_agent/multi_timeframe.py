"""Independent multi-timeframe SMC context, from CLOSED MT5 candles only.

Additional H4/M30/M15 observations never modify the v0.12 H1/M5 signal
algorithm. No consensus score is asserted to imply profitable trading.
All observations are read-only and require a coherent per-symbol live
clock from the XM DEMO snapshot. Broker clock offsets are provisional.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
import re

from .engine import Candle, macro_bias


# From broader market context to entry scale.
TF_SECONDS = (("H4", 14400), ("H1", 3600), ("M30", 1800),
              ("M15", 900), ("M5", 300))
EXTRA_TFS = ("H4", "M30", "M15")
MAX_AGE_MULTIPLIER = 2
OBSERVED_OFFSETS = frozenset((0, 7200, 10800))


@dataclass(frozen=True)
class FrameObservation:
    timeframe: str
    bias: str
    last_closed_utc: str | None
    age_seconds: float | None
    state: str
    explanation: str = ""

    def __post_init__(self):
        if self.timeframe not in dict(TF_SECONDS):
            raise ValueError("Unknown timeframe")
        if self.state != "OK" and self.bias != "NÃO AVALIADO":
            raise ValueError("Unavailable timeframe cannot state a directional bias")


@dataclass(frozen=True)
class MultiTimeframeContext:
    frames: tuple[FrameObservation, ...]
    labels: tuple[str, ...] = tuple(x[0] for x in TF_SECONDS)

    def __post_init__(self):
        if tuple(f.timeframe for f in self.frames) != self.labels:
            raise ValueError("Timeframes must appear exactly once in descending order")

    @property
    def available_count(self) -> int:
        return sum(f.state == "OK" for f in self.frames)

    @property
    def counts(self) -> dict[str, int]:
        return {direction: sum(f.bias == direction for f in self.frames)
                for direction in ("ALTA", "BAIXA", "NEUTRO")}

    @property
    def summary(self) -> str:
        c = self.counts
        return (f"Leitura {self.available_count}/5 períodos | "
                f"Alta {c['ALTA']} · Baixa {c['BAIXA']} · Neutro {c['NEUTRO']}")

    def to_log(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "timeframes": {
                frame.timeframe: {
                    "bias": frame.bias, "status": frame.state,
                    "closed_at_utc": frame.last_closed_utc,
                }
                for frame in self.frames
            }
        }


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None or dt.utcoffset() is None:
            return None
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _offset_seconds(label: Any) -> int | None:
    # Only live_clock.reconcile_live_clock-derived offsets are expected.
    if not isinstance(label, str):
        return None
    match = re.match(r"^UTC([+-])(\d\d):00 \(observado agora, provisório\)$",label)
    if not match:
        return None
    sign = 1 if match.group(1) == "+" else -1
    seconds = sign * int(match.group(2)) * 3600
    return seconds if seconds in OBSERVED_OFFSETS else None


def _unavailable(tf: str, reason: str,
                 closed_at: str | None = None,
                 age: float | None = None) -> FrameObservation:
    return FrameObservation(tf, "NÃO AVALIADO", closed_at,
                            age, "INDISPONIVEL", reason[:180])


def _bias_text(value: int) -> str:
    return "ALTA" if value > 0 else "BAIXA" if value < 0 else "NEUTRO"


def _validate_recency(*, tf: str, closed: datetime, observed_now: datetime,
                      tick_utc: datetime) -> float:
    duration = dict(TF_SECONDS)[tf]
    age = (observed_now - closed).total_seconds()
    # The last closed candle can never finish beyond current tick's instant.
    if (age < 0 or (closed - tick_utc).total_seconds() > 10
            or age > duration * MAX_AGE_MULTIPLIER + 60):
        raise ValueError("Candle não fechado, futuro ou antigo para este período")
    return round(age, 1)


def _snapshot_frame(tf: str, snapshot: Any, now: datetime,
                    tick: datetime) -> FrameObservation:
    name = {"H1": "h1_bias", "M5": "m5_bias"}[tf]
    last = {"H1": "last_closed_h1_utc", "M5": "last_closed_m5_utc"}[tf]
    closed_label = getattr(snapshot, last, None)
    closed = _timestamp(closed_label)
    direction = getattr(snapshot, name, "NÃO AVALIADO")
    if closed is None or direction not in ("ALTA", "BAIXA", "NEUTRO"):
        return _unavailable(tf, "Leitura principal incompleta")
    try:
        age = _validate_recency(tf=tf, closed=closed,
                                observed_now=now, tick_utc=tick)
    except ValueError as e:
        return _unavailable(tf, str(e), closed_label)
    return FrameObservation(tf, direction, closed.isoformat(), age, "OK")


def _extra_frame(tf: str, bars: list[Candle], *, offset: int,
                 now: datetime, tick: datetime) -> FrameObservation:
    if len(bars) < 50:
        return _unavailable(tf, "Histórico fechado insuficiente (mínimo 50 candles)")
    if any(a.time >= b.time for a, b in zip(bars, bars[1:])):
        return _unavailable(tf, "Candles fora de ordem ou repetidos")
    raw_close = bars[-1].time
    if raw_close.tzinfo is None or raw_close.utcoffset() is None:
        return _unavailable(tf, "Horário bruto sem fuso")
    raw_close = raw_close.astimezone(timezone.utc) + timedelta(seconds=dict(TF_SECONDS)[tf])
    # MT5 bars() excludes the currently forming bar via position 1.
    # Validate this claimed *close* is not ahead of the reconciled tick.
    closed = raw_close - timedelta(seconds=offset)
    try:
        age = _validate_recency(tf=tf, closed=closed,
                                observed_now=now, tick_utc=tick)
    except ValueError as exc:
        return _unavailable(tf, str(exc), closed.isoformat())
    direction = _bias_text(macro_bias(bars))
    return FrameObservation(tf, direction, closed.isoformat(), age, "OK")


def observe_timeframes(adapter: Any, snapshot: Any,
                       *, count: int = 160) -> MultiTimeframeContext:
    """Read supplementary timeframes for one symbol independently.

    Uses H1 and M5 already validated by capture() so the existing signal
    path remains unchanged and no duplicate H1/M5 history is requested.
    On H4/M30/M15 data failures, show the respective frame unavailable;
    do not fabricate alignment or silently require all frames to agree.
    """
    now = _timestamp(getattr(snapshot, "generated_utc", None))
    tick = _timestamp(getattr(snapshot, "quote_time_utc", None))
    offset = _offset_seconds(getattr(snapshot, "clock_offset_label", None))
    verified_demo = getattr(snapshot, "connected_to_demo", False) is True
    if not verified_demo or now is None or tick is None or offset is None:
        frames = tuple(_unavailable(tf, "Conta DEMO ou relógio não verificado")
                       for tf, _ in TF_SECONDS)
        return MultiTimeframeContext(frames)
    if (now - tick).total_seconds() < -10 or (now - tick).total_seconds() > 60:
        frames = tuple(_unavailable(tf, "Tick antigo/futuro; análise de períodos suspensa")
                       for tf, _ in TF_SECONDS)
        return MultiTimeframeContext(frames)
    if type(count) is not int or count < 50 or count > 500:
        raise ValueError("Invalid multi-timeframe history count")

    by_tf = {}
    for tf in ("H1", "M5"):
        by_tf[tf] = _snapshot_frame(tf, snapshot, now, tick)
    for tf in EXTRA_TFS:
        try:
            bars = adapter.bars(tf, count=count)
            by_tf[tf] = _extra_frame(tf, bars, offset=offset, now=now, tick=tick)
        except Exception as exc:
            by_tf[tf] = _unavailable(tf, f"Histórico {tf} indisponível: {exc}")
    return MultiTimeframeContext(tuple(by_tf[tf] for tf, _ in TF_SECONDS))
