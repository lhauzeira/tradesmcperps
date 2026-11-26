"""Read-only link between a newly observed SMC signal and XM DEMO preflight.

Uses the minimum broker lot to ask the MT5 calculator for a hypothetical
stop loss and margin. Never rounds a signal's SL/TP; rejects invalid
tick grids, stale signals, price drift, unverified sessions and all
brokerage execution. The computed minimum is NOT a proposed live order.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .alerts import SignalRecord
from .demo_preflight import (
    BrokerPreflightReport, DemoOrderHypothesis, estimate_demo_order
)
from .monitor_local import check_demo_account, EXPECTED_SERVER


def _num(v: Any) -> Decimal | None:
    try:
        if isinstance(v, bool):
            return None
        n=Decimal(str(v))
        return n if n.is_finite() and n > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _blocked(signal: SignalRecord, blockers: tuple[str, ...]) -> BrokerPreflightReport:
    return BrokerPreflightReport(
        symbol=signal.symbol, signal_id=signal.event_id,
        status="BLOQUEADO_PARA_ORDENS",blockers=blockers,
        account_currency=None,entry_bid=None,entry_ask=None,
        theoretical_loss_account_currency=None,
        estimated_margin_account_currency=None,
        assumed_cost_reserve_account_currency=None,
        max_risk_budget_account_currency=None,
        number_open_positions=None,number_pending_orders=None
    )


def probe_research_signal(
    mt5: Any, signal: SignalRecord, snapshot: Any,
    *, now: datetime | None = None
) -> BrokerPreflightReport:
    """Always read-only; no order_send/order_check calls.

    Rechecks the XM demo account BEFORE querying broker specifications,
    then validates the signal is current and belongs to the snapshot.
    """
    if now is None:
        now=datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Datetime UTC com fuso obrigatório")
    now=now.astimezone(timezone.utc)
    check_demo_account(mt5.account_info(),mt5,expected_server=EXPECTED_SERVER)

    blockers=[]
    if not isinstance(signal,SignalRecord) or signal.timeframe!="M5":
        raise ValueError("Somente SignalRecord M5 da pesquisa")
    if signal.symbol!=getattr(snapshot,"symbol",None):
        return _blocked(signal,("ATIVO_DO_SINAL_DIVERGENTE",))
    if getattr(snapshot,"connected_to_demo",None) is not True:
        return _blocked(signal,("EVIDENCIA_DEMO_INVALIDA",))
    signal_age=(now-signal.candle_closed_at.astimezone(timezone.utc)).total_seconds()
    # A fresh M5 close can be inspected within its next bar, not indefinitely
    # after a restart or outside the market's current session.
    if signal_age < 0 or signal_age > 330:
        blockers.append("SINAL_M5_ANTIGO_OU_FUTURO")
    atr=_num(getattr(snapshot,"m5_atr_price",None))
    if atr is None:
        blockers.append("ATR_M5_AUSENTE")
    bid=_num(getattr(snapshot,"quote_bid",None))
    ask=_num(getattr(snapshot,"quote_ask",None))
    if bid is None or ask is None or ask < bid:
        blockers.append("COTACAO_ATUAL_INVALIDA")
    elif atr is not None:
        reference=ask if signal.side=="buy" else bid
        if abs(reference-Decimal(str(signal.entry)))>atr*Decimal("0.50"):
            blockers.append("PRECO_DISTANTE_DA_ENTRADA_TEO RICA".replace(" ","_"))
    if blockers:
        return _blocked(signal,tuple(blockers))

    spec=mt5.symbol_info(signal.symbol)
    minimum=_num(getattr(spec,"volume_min",None)) if spec is not None else None
    if minimum is None:
        return _blocked(signal,("LOTE_MINIMO_MT5_INDISPONIVEL",))
    hypothetical=DemoOrderHypothesis(
        signal_id=signal.event_id,symbol=signal.symbol,side=signal.side,
        volume=minimum,stop=Decimal(str(signal.stop)),
        target=Decimal(str(signal.target))
    )
    # estimate_demo_order re-verifies account identity, broker exposure,
    # margin, stop level, instrument trade_mode and tick recency. Its
    # report ALWAYS has can_submit_orders=False, regardless of inputs.
    return estimate_demo_order(
        mt5,hypothetical,now=now,market_evidence=snapshot
    )
