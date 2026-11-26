"""Broker request BLUEPRINTS only — never call MetaTrader5.order_send.

Requires explicit, verified-in-the-future MT5 numeric constants and
instrument parameters. Generates request-shaped dictionaries to test
correct fields for MARKET opening/closing on a *fictional* broker, with
no actual order submission, broker login or trading permission.

This module does not verify sessions, account currency, losses, margin,
filling-mode compatibility, spread freshness or broker retcodes. Those
MUST be validated by the later demo execution gateway. It is forbidden
to interpret its previews as approved trade requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
import re


def _d(value: Any, *, positive: bool = True) -> Decimal:
    if isinstance(value,bool):
        raise ValueError("Invalid numeric field")
    try:
        v=Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid numeric field") from None
    if not v.is_finite() or (v <= 0 if positive else v < 0):
        raise ValueError("Invalid numeric field")
    return v


def _code(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Missing or invalid MT5 code: {name}")
    return value


def _on_grid(value: Decimal, tick: Decimal) -> bool:
    ratio=value/tick
    return ratio==ratio.to_integral_value()


@dataclass(frozen=True)
class MT5RequestCodes:
    deal: int
    buy: int
    sell: int
    time_gtc: int

    def __post_init__(self):
        for name in ("deal","buy","sell","time_gtc"):
            _code(getattr(self,name),name)
        if self.buy==self.sell:
            raise ValueError("Buy and sell codes must differ")


@dataclass(frozen=True)
class DraftInstrumentRules:
    """Caller-supplied mock symbol info, not a verified broker contract."""
    symbol: str
    tick_size: Decimal
    point: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    stops_level_points: int
    filling_mode_code: int

    def __post_init__(self):
        if (not isinstance(self.symbol,str) or
                not re.fullmatch(r"[A-Za-z0-9._#-]{1,40}",self.symbol)):
            raise ValueError("Invalid instrument symbol")
        for field in ("tick_size","point","volume_min",
                      "volume_max","volume_step"):
            _d(getattr(self,field))
        _code(self.filling_mode_code,"filling_mode_code")
        _code(self.stops_level_points,"stops_level_points")
        if _d(self.volume_max)<_d(self.volume_min):
            raise ValueError("Maximum volume below minimum")


@dataclass(frozen=True)
class DraftQuote:
    symbol: str
    bid: Decimal
    ask: Decimal

    def __post_init__(self):
        bid=_d(self.bid)
        ask=_d(self.ask)
        if not self.symbol or ask<bid:
            raise ValueError("Invalid quote")


@dataclass(frozen=True)
class OpenBlueprint:
    signal_id: str
    symbol: str
    side: str
    volume: Decimal
    stop: Decimal
    target: Decimal
    deviation_points: int = 20

    def __post_init__(self):
        if (not isinstance(self.signal_id,str) or
                not re.fullmatch(r"[A-Za-z0-9._-]{1,80}",self.signal_id)):
            raise ValueError("Invalid signal ID")
        if self.side not in ("buy","sell") or not self.symbol:
            raise ValueError("Invalid side/symbol")
        for value in (self.volume,self.stop,self.target):
            _d(value)
        if type(self.deviation_points) is not int or not 0<=self.deviation_points<=100:
            raise ValueError("Invalid deviation limit")


@dataclass(frozen=True)
class CloseBlueprint:
    signal_id: str
    symbol: str
    original_side: str
    position_ticket: int
    position_volume: Decimal
    deviation_points: int = 20

    def __post_init__(self):
        if not isinstance(self.signal_id,str) or not re.fullmatch(
                r"[A-Za-z0-9._-]{1,80}",self.signal_id):
            raise ValueError("Invalid signal ID")
        if not self.symbol or self.original_side not in ("buy","sell"):
            raise ValueError("Invalid position side")
        if type(self.position_ticket) is not int or self.position_ticket<=0:
            raise ValueError("A position ticket is mandatory to close")
        _d(self.position_volume)
        if type(self.deviation_points) is not int or not 0<=self.deviation_points<=100:
            raise ValueError("Invalid deviation limit")


@dataclass(frozen=True)
class OrderRequestPreview:
    """Informational request fields ONLY, not executable permission."""
    kind: str
    symbol: str
    request_items: tuple[tuple[str, Any], ...]
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.can_submit_orders:
            raise ValueError("Blueprint never authorizes order_send")
        if self.kind not in ("OPEN_FICTITIOUS","CLOSE_FICTITIOUS"):
            raise ValueError("Only fictitious previews allowed")

    def as_dict(self) -> dict[str, Any]:
        return dict(self.request_items)


def _volume_ok(volume: Decimal, spec: DraftInstrumentRules):
    mn,mx,step=(_d(spec.volume_min),_d(spec.volume_max),_d(spec.volume_step))
    if not mn<=volume<=mx or not _on_grid(volume-mn,step):
        raise ValueError("Volume outside instrument volume grid")


def _base(side: str, volume: Decimal, quote: DraftQuote,
          spec: DraftInstrumentRules, codes: MT5RequestCodes,
          deviation: int, signal_id: str) -> dict[str, Any]:
    if quote.symbol!=spec.symbol:
        raise ValueError("Quote and symbol mismatch")
    _volume_ok(volume,spec)
    price=_d(quote.ask if side=="buy" else quote.bid)
    if not _on_grid(price,_d(spec.tick_size)):
        raise ValueError("Market price not on tick grid")
    return {
        "action":codes.deal, "symbol":spec.symbol,
        "type":codes.buy if side=="buy" else codes.sell,
        "volume":float(volume), "price":float(price),
        "deviation":deviation, "type_time":codes.time_gtc,
        "type_filling":spec.filling_mode_code,
        "comment":"SMC_RESEARCH_"+signal_id[:12],
    }


def preview_open_request(
    proposal: OpenBlueprint, quote: DraftQuote,
    spec: DraftInstrumentRules, codes: MT5RequestCodes
) -> OrderRequestPreview:
    if proposal.symbol!=spec.symbol:
        raise ValueError("Open symbol mismatch")
    vol=_d(proposal.volume)
    req=_base(proposal.side,vol,quote,spec,codes,
              proposal.deviation_points,proposal.signal_id)
    sl,tp=_d(proposal.stop),_d(proposal.target)
    tick=_d(spec.tick_size)
    if not _on_grid(sl,tick) or not _on_grid(tp,tick):
        raise ValueError("Stop or target outside symbol tick grid")
    bid,ask=_d(quote.bid),_d(quote.ask)
    minimum=_d(spec.point)*spec.stops_level_points
    if proposal.side=="buy":
        if not (sl<bid and tp>ask) or bid-sl<minimum or tp-bid<minimum:
            raise ValueError("BUY stop/target not protectively placed")
    else:
        if not (sl>ask and tp<bid) or sl-ask<minimum or ask-tp<minimum:
            raise ValueError("SELL stop/target not protectively placed")
    req["sl"],req["tp"]=float(sl),float(tp)
    return OrderRequestPreview(
        "OPEN_FICTITIOUS",spec.symbol,tuple(req.items())
    )


def preview_close_request(
    proposal: CloseBlueprint, quote: DraftQuote,
    spec: DraftInstrumentRules, codes: MT5RequestCodes
) -> OrderRequestPreview:
    if proposal.symbol!=spec.symbol:
        raise ValueError("Close symbol mismatch")
    # A long POSITION is closed by SELL at Bid; short by BUY at Ask.
    close_side="sell" if proposal.original_side=="buy" else "buy"
    req=_base(close_side,_d(proposal.position_volume),
              quote,spec,codes,proposal.deviation_points,proposal.signal_id)
    req["position"]=proposal.position_ticket
    return OrderRequestPreview(
        "CLOSE_FICTITIOUS",spec.symbol,tuple(req.items())
    )


def fabricated_preview() -> str:
    mock=DraftInstrumentRules(
        "FICTICIO",Decimal(".01"),Decimal(".01"),
        Decimal(".01"),Decimal("10"),Decimal(".01"),
        stops_level_points=20,filling_mode_code=1
    )
    fake_codes=MT5RequestCodes(deal=1,buy=0,sell=1,time_gtc=0)
    q=DraftQuote("FICTICIO",Decimal("100"),Decimal("100.2"))
    opened=preview_open_request(
        OpenBlueprint("EXAMPLE-001","FICTICIO","buy",
                      Decimal(".01"),Decimal("99"),Decimal("103")),
        q,mock,fake_codes
    )
    closed=preview_close_request(
        CloseBlueprint("EXAMPLE-001","FICTICIO","buy",12345,
                       Decimal(".01")),q,mock,fake_codes
    )
    return (
        "SOLICITACOES FICTICIAS — NENHUMA CONTA/ORDEM REAL OU DEMO\n"
        f"Campos abertura: {opened.as_dict()}\n"
        f"Campos fechamento: {closed.as_dict()}\n"
        "NENHUM MT5.order_send FOI CHAMADO. PREENCHIMENTO NAO COMPROVADO."
    )


if __name__ == "__main__":
    print(fabricated_preview())
