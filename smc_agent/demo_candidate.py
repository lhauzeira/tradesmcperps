"""End-to-end XM DEMO candidate: SMC M5 -> native-risk -> OPEN PREVIEW.

READ ONLY. Never import MetaTrader5/order_send, never submit a request,
never close any actual account positions. The preview is diagnostic
output ONLY, with can_submit_orders=False by construction.

A broker's symbol_info.filling_mode is a bitmask. It MUST NOT be
passed directly as ORDER_FILLING_* enum: those encodings differ.
Support IOC or FOK only when the MT5 module explicitly reports both
a matching symbol flag and a documented request enum. Unknown
filling-mode data blocks the preview. All sessions still require
independent per-instrument authoritative verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .alerts import SignalRecord
from .demo_signal_probe import probe_research_signal
from .demo_preflight import BrokerPreflightReport
from .monitor_local import EXPECTED_SERVER, check_demo_account
from .mt5_request_preview import (
    MT5RequestCodes, DraftInstrumentRules, DraftQuote,
    OpenBlueprint, OrderRequestPreview, preview_open_request
)

# These exclusions are *permanent* hard blocks but may still be shown
# alongside a non-executable diagnostic preview.
_EXPECTED_INCOMPLETE = frozenset({
    "SESSOES_FERIADOS_NAO_VERIFICADOS",
    "CUSTOS_REAIS_E_SLIPPAGE_NAO_VERIFICADOS",
    "PERDA_DIARIA_REAL_NAO_RECONCILIADA",
    "EXECUCAO_DE_ORDENS_DESABILITADA",
})


@dataclass(frozen=True)
class DemoCandidate:
    signal_id: str
    symbol: str
    report: BrokerPreflightReport
    preview: OrderRequestPreview | None
    blockers: tuple[str, ...]
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.can_submit_orders:
            raise ValueError("Candidate analysis NEVER authorizes order submission")


def _broker_code(mt5: Any, name: str) -> int:
    value=getattr(mt5,name,None)
    if type(value) is not int or value<0:
        raise ValueError(f"MT5 constant unavailable: {name}")
    return value


def _filling_mode(mt5: Any, info: Any) -> int:
    """Only explicit IO(C) / FOK flags; no assumed RETURN fallback."""
    mask = getattr(info,"filling_mode",None)
    if type(mask) is not int or mask<0:
        raise ValueError("SYMBOL_FILLING_FLAGS_UNVERIFIED")
    for flag_name,order_name in (
        ("SYMBOL_FILLING_IOC","ORDER_FILLING_IOC"),
        ("SYMBOL_FILLING_FOK","ORDER_FILLING_FOK"),
    ):
        flag=_broker_code(mt5,flag_name)
        order_mode=_broker_code(mt5,order_name)
        if flag>0 and mask & flag:
            return order_mode
    raise ValueError("NO_VERIFIED_IOC_OR_FOK_FILLING_MODE")


def build_demo_open_candidate(
    mt5: Any, signal: SignalRecord, snapshot: Any,
    *, now: datetime | None = None
) -> DemoCandidate:
    """Prepare an OPEN request blueprint only. Do not invoke order_send."""
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Timezone-aware now required")
    # Verify before all symbol/quote/risk reads. probe repeats this.
    check_demo_account(mt5.account_info(),mt5,expected_server=EXPECTED_SERVER)
    preflight=probe_research_signal(mt5,signal,snapshot,now=instant)
    if any(code not in _EXPECTED_INCOMPLETE for code in preflight.blockers):
        return DemoCandidate(
            signal.event_id,signal.symbol,preflight,None,
            preflight.blockers+("PREVIA_NAO_GERADA_FALHA_DADOS",)
        )
    try:
        info=mt5.symbol_info(signal.symbol)
        if info is None:
            raise ValueError("Broker symbol specifications unavailable")
        # Explicit flags: the MT5 mode flag and order filling enum differ.
        fill=_filling_mode(mt5,info)
        codes=MT5RequestCodes(
            deal=_broker_code(mt5,"TRADE_ACTION_DEAL"),
            buy=_broker_code(mt5,"ORDER_TYPE_BUY"),
            sell=_broker_code(mt5,"ORDER_TYPE_SELL"),
            time_gtc=_broker_code(mt5,"ORDER_TIME_GTC")
        )
        rules=DraftInstrumentRules(
            symbol=signal.symbol,
            tick_size=Decimal(str(info.trade_tick_size)),
            point=Decimal(str(info.point)),
            volume_min=Decimal(str(info.volume_min)),
            volume_max=Decimal(str(info.volume_max)),
            volume_step=Decimal(str(info.volume_step)),
            stops_level_points=info.trade_stops_level,
            filling_mode_code=fill,
        )
        quote=DraftQuote(
            signal.symbol,
            bid=preflight.entry_bid,
            ask=preflight.entry_ask,
        )
        preview=preview_open_request(
            OpenBlueprint(
                signal_id=signal.event_id,
                symbol=signal.symbol,side=signal.side,
                volume=Decimal(str(info.volume_min)),
                stop=Decimal(str(signal.stop)),
                target=Decimal(str(signal.target)),
            ),quote,rules,codes
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError) as exc:
        # Diagnostic error strings are NOT raw account data.
        return DemoCandidate(
            signal.event_id,signal.symbol,preflight,None,
            preflight.blockers+("PREVIA_BLOQUEADA_INCOMPATIBILIDADE_MT5",)
        )
    # Recheck demo identity after all read-only broker calls.
    check_demo_account(mt5.account_info(),mt5,expected_server=EXPECTED_SERVER)
    return DemoCandidate(
        signal.event_id,signal.symbol,preflight,preview,preflight.blockers
    )
