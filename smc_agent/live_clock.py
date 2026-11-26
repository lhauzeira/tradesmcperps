"""Provisional LIVE-only XM GOLD clock reconciliation from independent tick/bar data.

The MT5 Python client gives numeric timestamps. At the user's XM DEMO
terminal on 2026-11-26, a read-only diagnostic showed raw tick timestamps
about +02:00 relative to the PC's UTC and raw M5/H1 opens aligned with
that observation. This code does NOT assume that GMT+2 is always true:
it requires a *fresh* tick, an hour-like candidate offset, synchronized
closed M5/H1 bars and a live DEMO account checked by the caller.

A result is an ephemeral research observation, NOT a verified historical
timezone. Never use this resolver to rewrite June ticks, validate backtests,
place orders or claim broker execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite


# Candidates to TEST, not offsets to ASSUME. The current XM demo screenshot
# demonstrated +02:00, while its documentation mentions seasonal GMT+3.
# 0 also permits terminals returning correctly UTC-tagged epochs.
CANDIDATE_OFFSETS_SECONDS = (0, 7200, 10800)
MAX_TICK_LAG_SECONDS = 60
MAX_TICK_FUTURE_SECONDS = 10
MAX_M5_AGE_SECONDS = 900
MAX_H1_AGE_SECONDS = 7200


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} precisa de fuso horário")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class LiveClockObservation:
    observed_offset_seconds: int
    tick_utc: datetime
    m5_closed_utc: datetime
    h1_closed_utc: datetime
    tick_lag_seconds: float
    m5_age_seconds: float
    h1_age_seconds: float
    confidence: str = "LIVE_TICK_M5_H1_COHERENT_NOT_HISTORICALLY_VERIFIED"

    @property
    def offset_label(self) -> str:
        hours = self.observed_offset_seconds // 3600
        return f"UTC{hours:+03d}:00 (observado agora, provisório)"


def reconcile_live_clock(
    *, now: datetime, raw_tick_seconds: int | float,
    raw_m5_open: datetime, raw_h1_open: datetime,
) -> LiveClockObservation:
    """Validate this scan independently; block on missing/mismatched times.

    The raw timestamps are interpreted like UTC for arithmetic ONLY, before
    removing a candidate observed offset. No broker timezone is silently
    asserted. Reject stale/future ticks, non-closed bars, inconsistent H1,
    and unknown fractional/non-hour offset differences.
    """
    now = _utc(now, "now")
    m5_open = _utc(raw_m5_open, "raw_m5_open")
    h1_open = _utc(raw_h1_open, "raw_h1_open")
    if (isinstance(raw_tick_seconds, bool)
            or not isinstance(raw_tick_seconds, (int, float))
            or not isfinite(raw_tick_seconds)
            or raw_tick_seconds <= 0):
        raise RuntimeError("Tick GOLD ausente ou com horário inválido; análise bloqueada")

    raw_tick = datetime.fromtimestamp(raw_tick_seconds, timezone.utc)
    delta = (raw_tick - now).total_seconds()
    chosen = min(CANDIDATE_OFFSETS_SECONDS, key=lambda x: abs(delta - x))
    lag = chosen - delta  # Positive = adjusted tick earlier than now
    if not -MAX_TICK_FUTURE_SECONDS <= lag <= MAX_TICK_LAG_SECONDS:
        raise RuntimeError(
            "Horários MT5/PC divergentes ou tick GOLD antigo; "
            "sem correção automática fora dos limites seguros. "
            "Rode VERIFICAR_HORARIO_XM_DEMO.bat."
        )

    observed_offset = timedelta(seconds=chosen)
    tick_utc = raw_tick - observed_offset
    m5_closed = m5_open + timedelta(seconds=300) - observed_offset
    h1_closed = h1_open + timedelta(seconds=3600) - observed_offset
    m5_age = (now - m5_closed).total_seconds()
    h1_age = (now - h1_closed).total_seconds()

    # Last CLOSED M5/H1 bars must be aligned and not in the future. These
    # are independently sampled from copy_rates_from_pos(position=1).
    if int(m5_closed.timestamp()) % 300 != 0 or int(h1_closed.timestamp()) % 3600 != 0:
        raise RuntimeError(
            "Alinhamento M5/H1 inesperado após correção; análise bloqueada"
        )
    if not 0 <= m5_age <= MAX_M5_AGE_SECONDS:
        raise RuntimeError(
            f"Candle M5 não está recente após conciliação ({m5_age:.0f} s); "
            "sem sinal de pesquisa."
        )
    if not 0 <= h1_age <= MAX_H1_AGE_SECONDS:
        raise RuntimeError(
            f"Candle H1 não está coerente após conciliação ({h1_age:.0f} s); "
            "sem sinal de pesquisa."
        )
    # The last tick cannot be earlier than the close of the latest completed
    # bars. Allow very short sampling races, not minutes of disagreement.
    if (m5_closed - tick_utc).total_seconds() > 10 or (h1_closed - tick_utc).total_seconds() > 10:
        raise RuntimeError(
            "Tick GOLD e candles fechados não confirmam a mesma sequência temporal"
        )
    if not h1_open < m5_open + timedelta(hours=2):
        # This condition is intentionally conservative for spectacular
        # history mismatches, but normally true for latest closed M5/H1.
        raise RuntimeError("Ordem de abertura entre H1 e M5 não coerente")

    return LiveClockObservation(
        observed_offset_seconds=chosen,
        tick_utc=tick_utc,
        m5_closed_utc=m5_closed,
        h1_closed_utc=h1_closed,
        tick_lag_seconds=round(lag, 2),
        m5_age_seconds=round(m5_age, 2),
        h1_age_seconds=round(h1_age, 2),
    )
