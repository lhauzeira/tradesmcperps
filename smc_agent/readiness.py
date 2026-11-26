"""Read-only pre-execution quality checks for individual MT5 symbols.

NO account credentials, positions, balance, orders, live order sizing or
execution API. This module cannot grant order permission, even when all
price quality checks pass. Sessions and holiday schedules are NOT verified
by MT5's symbol trade_mode; require a separate broker calendar later.

The spread/ATR ratio is experimental diagnostics, NOT a validated threshold
for GOLD, US100, US500, forex or other markets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class ReadinessPolicy:
    max_tick_age_seconds: float = 15.0
    max_future_quote_seconds: float = 3.0
    max_spread_to_m5_atr: float = 0.25

    def __post_init__(self) -> None:
        for key in ("max_tick_age_seconds", "max_future_quote_seconds",
                    "max_spread_to_m5_atr"):
            value = getattr(self, key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or value <= 0):
                raise ValueError(f"Invalid readiness policy: {key}")


@dataclass(frozen=True)
class ReadinessReport:
    symbol: str
    status: str
    block_codes: tuple[str, ...]
    tick_age_seconds: float | None
    spread_to_m5_atr: float | None
    session_verified: bool
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.can_submit_orders:
            raise ValueError("v0.13 cannot authorize orders")


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _positive(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (float, int))
            and isfinite(value) and value > 0)


def evaluate_readiness(
    snapshot: Any,
    spec: Any,
    *,
    trade_mode_full: int | None,
    session_verified: bool = False,
    policy: ReadinessPolicy = ReadinessPolicy(),
) -> ReadinessReport:
    """Fail closed, independently per symbol.

    session_verified is ONLY true once a future integration verifies the
    broker-specific session/holiday schedule. The v0.13 monitor always
    passes False: no simulation state is mistaken for trade permission.
    """
    symbol = getattr(snapshot, "symbol", "?")
    blocks = []
    if not getattr(snapshot, "connected_to_demo", False):
        blocks.append("CONTA_DEMO_NAO_CONFIRMADA")
    offset = getattr(snapshot, "clock_offset_label", None)
    if not isinstance(offset, str) or not offset.startswith("UTC"):
        blocks.append("RELOGIO_NAO_CONCILIADO")

    tick_age = None
    generated = _utc(getattr(snapshot, "generated_utc", None))
    quote_time = _utc(getattr(snapshot, "quote_time_utc", None))
    if generated is None or quote_time is None:
        blocks.append("HORARIO_COTACAO_INVALIDO")
    else:
        tick_age = (generated - quote_time).total_seconds()
        if (tick_age > policy.max_tick_age_seconds
                or tick_age < -policy.max_future_quote_seconds):
            blocks.append("TICK_DESATUALIZADO_OU_FUTURO")

    bid, ask = getattr(snapshot, "quote_bid", None), getattr(snapshot, "quote_ask", None)
    atr = getattr(snapshot, "m5_atr_price", None)
    ratio = None
    if not _positive(bid) or not _positive(ask) or ask < bid:
        blocks.append("COTACAO_BID_ASK_INVALIDA")
    elif not _positive(atr):
        blocks.append("ATR_M5_INDISPONIVEL")
    else:
        ratio = (ask - bid) / atr
        if ratio > policy.max_spread_to_m5_atr:
            blocks.append("SPREAD_ELEVADO_RELATIVO_ATR")

    # Trading mode is a broker-reported field, NOT proof of a live session.
    actual_mode = getattr(spec, "trade_mode", None)
    if (type(trade_mode_full) is not int or
            type(actual_mode) is not int or actual_mode != trade_mode_full):
        blocks.append("MODO_NEGOCIACAO_NAO_CONFIRMADO")

    # Deliberately no inference from weekdays, ticks or asset names.
    if not session_verified:
        blocks.append("SESSAO_OU_FERIADO_NAO_VERIFICADO")

    # Financial spec may be absent even for a quoting-only instrument;
    # never allow a future order-preflight to rely on unverified tick size.
    required = ("trade_tick_size", "trade_tick_value",
                "volume_min", "volume_step", "volume_max", "point")
    if spec is None or any(not _positive(getattr(spec, k, None)) for k in required):
        blocks.append("CONTRATO_OU_TICK_VALUE_NAO_CONFIRMADO")
    else:
        vmin, vmax = spec.volume_min, spec.volume_max
        if vmin > vmax:
            blocks.append("LIMITES_VOLUME_INCOERENTES")

    return ReadinessReport(
        symbol=str(symbol),
        status="BLOQUEADO_PARA_EXECUCAO" if blocks else "DADOS_PRELIMINARES_APENAS",
        block_codes=tuple(blocks),
        tick_age_seconds=None if tick_age is None else round(tick_age, 2),
        spread_to_m5_atr=None if ratio is None else round(ratio, 3),
        session_verified=session_verified,
        can_submit_orders=False,
    )
