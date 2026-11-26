"""Sanitized, READ-ONLY XM DEMO terminal/symbol specifications inventory.

No account ID, login, password, equity, balance, positions' personal
data, order requests or private keys are returned or written anywhere.

This scan is not a holiday calendar or order permission. A symbol's
trade_mode=FULL does not prove its CFD market is currently open.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .monitor_local import check_demo_account
from .multi_monitor import read_symbol_list


def _positive(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        d=Decimal(str(value))
        if not d.is_finite() or d <= 0:
            return None
        return str(d)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _digits(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 10 else None


def audit_demo_instruments(mt5: Any, symbols: tuple[str,...]) -> dict:
    """Account verification must precede ALL instrument reads."""
    acc=mt5.account_info()
    check_demo_account(acc, mt5)
    currency=getattr(acc,"currency",None)
    if type(currency) is not str or len(currency)!=3 or not currency.isupper():
        raise RuntimeError("Moeda da conta DEMO indisponível")
    if not isinstance(symbols,tuple) or not 1<=len(symbols)<=12:
        raise ValueError("Lista de instrumentos inválida")
    if len(set(symbols))!=len(symbols):
        raise ValueError("Instrumentos duplicados")
    inspected=[]
    for symbol in symbols:
        if not isinstance(symbol,str) or not symbol.strip() or len(symbol)>40:
            raise ValueError("Símbolo inválido")
        if not mt5.symbol_select(symbol,True):
            inspected.append({"symbol":symbol,"state":"INDISPONIVEL"})
            continue
        info=mt5.symbol_info(symbol)
        tick=mt5.symbol_info_tick(symbol)
        if info is None:
            inspected.append({"symbol":symbol,"state":"SEM_ESPECIFICACOES"})
            continue
        full=getattr(mt5,"SYMBOL_TRADE_MODE_FULL",None)
        mode=getattr(info,"trade_mode",None)
        record={
            "symbol":symbol,
            "state":"DADOS_RECEBIDOS_SEM_CONFIRMACAO_DE_SESSAO",
            "price_digits":_digits(getattr(info,"digits",None)),
            "point":_positive(getattr(info,"point",None)),
            "tick_size":_positive(getattr(info,"trade_tick_size",None)),
            "tick_value_loss":_positive(getattr(info,"trade_tick_value_loss",None)),
            "volume_min":_positive(getattr(info,"volume_min",None)),
            "volume_max":_positive(getattr(info,"volume_max",None)),
            "volume_step":_positive(getattr(info,"volume_step",None)),
            "trade_stops_level":getattr(info,"trade_stops_level",None)
                if type(getattr(info,"trade_stops_level",None)) is int else None,
            "trade_mode_full":type(full) is int and type(mode) is int and full==mode,
            "bid":_positive(getattr(tick,"bid",None)) if tick is not None else None,
            "ask":_positive(getattr(tick,"ask",None)) if tick is not None else None,
            "holiday_session_verified":False,
            "orders_enabled":False,
        }
        inspected.append(record)
    return {
        "source":"XMGlobal-MT5 5 DEMO — inventário somente leitura",
        "currency":currency,
        "instruments":inspected,
        "orders_sent":0,
        "note":"Não inclui identidade da conta, não comprova sessão/feriado nem autoriza ordens"
    }


def print_sanitized_report(report: dict) -> None:
    print("INVENTARIO XM DEMO — SOMENTE LEITURA. ZERO ORDENS.")
    print("Moeda da conta:",report["currency"])
    for row in report["instruments"]:
        print()
        print(row["symbol"],"—",row["state"])
        for field in (
            "price_digits","tick_size","tick_value_loss","volume_min",
            "volume_max","volume_step","trade_stops_level",
            "trade_mode_full","bid","ask"
        ):
            if field in row:
                print(" ",field,"=",row[field])
    print("ATENCAO: horários especiais e feriados NAO verificados.")


def diagnose_open_demo(*, root: Path | None = None) -> dict:
    """Explicit live read-only operation; no order send and no telemetry."""
    from .adapters import MT5Adapter
    root=root or Path.cwd()
    symbols=read_symbol_list(root/"ATIVOS_DEMO.txt")
    module=MT5Adapter(symbols[0]).mt5
    if not module.initialize():
        raise RuntimeError("Falha ao abrir terminal XM DEMO")
    try:
        result=audit_demo_instruments(module,symbols)
        print_sanitized_report(result)
        return result
    finally:
        module.shutdown()


if __name__=="__main__":
    diagnose_open_demo()
