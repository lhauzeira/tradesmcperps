"""Safe read-only MT5 timestamp diagnosis for XM DEMO/GOLD.

The time fields returned by the terminal are EPOCH-LIKE integers. MT5's
published documentation describes UTC, but a broker/platform discrepancy
can place displayed bar times ahead of system UTC. This tool NEVER
autocorrects a timestamp or authorizes a trading signal. It only compares
observations and shows the user a minimal, privacy-safe diagnostic.

No credentials, account number, balance, customer name, order or trade
information is queried or displayed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from .monitor_local import EXPECTED_SERVER, check_demo_account


def _read_time(records, name: str) -> int:
    if records is None or len(records) == 0:
        raise RuntimeError(f"MT5 não retornou candles {name} para diagnóstico")
    times = [int(item["time"]) for item in records]
    if any(v <= 0 for v in times):
        raise RuntimeError(f"Carimbo de tempo inválido em {name}")
    return max(times)


def _interpret_raw_epoch(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def _format_delta(seconds: float | None) -> str:
    if seconds is None:
        return "INDISPONÍVEL"
    return f"{seconds:+.1f} s ({seconds / 3600:+.2f} h)"


@dataclass(frozen=True)
class ClockDiagnostic:
    system_utc: str
    m5_last_closed_open_raw_as_utc: str
    m5_last_closed_end_raw_as_utc: str
    h1_last_closed_open_raw_as_utc: str
    h1_last_closed_end_raw_as_utc: str
    tick_raw_as_utc: str | None
    difference_m5_end_minus_system_seconds: float
    difference_tick_minus_system_seconds: float | None
    status: str

    def report(self) -> str:
        return "\n".join((
            "=== DIAGNÓSTICO DE HORÁRIO: XM DEMO / GOLD ===",
            "Somente leitura. Nenhuma ordem enviada.",
            "Nenhum número de conta, senha, saldo ou posição exibidos.",
            "",
            f"Relógio Windows interpretado em UTC: {self.system_utc}",
            f"M5 anterior, abertura BRUTA interpretada como UTC: {self.m5_last_closed_open_raw_as_utc}",
            f"M5 anterior, fechamento BRUTO interpretado como UTC: {self.m5_last_closed_end_raw_as_utc}",
            f"H1 anterior, abertura BRUTA interpretada como UTC: {self.h1_last_closed_open_raw_as_utc}",
            f"H1 anterior, fechamento BRUTO interpretado como UTC: {self.h1_last_closed_end_raw_as_utc}",
            f"Último tick BRUTO interpretado como UTC: {self.tick_raw_as_utc or 'INDISPONÍVEL'}",
            f"Fechamento M5 bruto menos UTC do PC: {_format_delta(self.difference_m5_end_minus_system_seconds)}",
            f"Tick bruto menos UTC do PC: {_format_delta(self.difference_tick_minus_system_seconds)}",
            "",
            f"Estado: {self.status}",
            "Importante: 'interpretado como UTC' não comprova o fuso real do servidor.",
            "Não mude o relógio do Windows nem force deslocamento horário no robô.",
            "Para prosseguir, envie somente o texto deste diagnóstico; não envie credenciais."
        ))


def read_clock(mt5, *, symbol: str, now: datetime,
               expected_server: str = EXPECTED_SERVER) -> ClockDiagnostic:
    """Collect just clocks + raw bar timestamps from a verified demo account."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Horário de referência precisa incluir fuso")
    now = now.astimezone(timezone.utc)
    if symbol != "GOLD":
        raise ValueError("Diagnóstico limitado ao símbolo GOLD")
    # Check account before any other terminal quote/history reads.
    check_demo_account(mt5.account_info(), mt5, expected_server=expected_server)
    m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, 2)
    h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, 2)
    last_m5 = _read_time(m5, "M5")
    last_h1 = _read_time(h1, "H1")
    m5_end = last_m5 + 300
    h1_end = last_h1 + 3600
    m5_delta = m5_end - now.timestamp()
    tick_time = None
    current = mt5.symbol_info_tick(symbol)
    if current is not None:
        raw = getattr(current, "time", None)
        if isinstance(raw, (int, float)) and isfinite(raw) and raw > 0:
            tick_time = int(raw)
    tick_delta = tick_time - now.timestamp() if tick_time is not None else None

    if m5_delta > 90:
        status = "M5 NO FUTURO: NÃO GERAR SINAIS; VALIDAR TEMPOS DO SERVIDOR"
    elif m5_delta < -900:
        status = "M5 ANTIGO: NÃO GERAR SINAIS; DADOS DESATUALIZADOS OU MERCADO FECHADO"
    elif tick_delta is not None and tick_delta > 90:
        status = "TICK NO FUTURO: VERIFICAR FUSO; NÃO GERAR SINAIS"
    else:
        status = "SEM ANOMALIA FUTURA ÓBVIA; AINDA REQUER VERIFICAÇÃO DO TERMINAL"

    return ClockDiagnostic(
        system_utc=now.isoformat(),
        m5_last_closed_open_raw_as_utc=_interpret_raw_epoch(last_m5),
        m5_last_closed_end_raw_as_utc=_interpret_raw_epoch(m5_end),
        h1_last_closed_open_raw_as_utc=_interpret_raw_epoch(last_h1),
        h1_last_closed_end_raw_as_utc=_interpret_raw_epoch(h1_end),
        tick_raw_as_utc=_interpret_raw_epoch(tick_time) if tick_time else None,
        difference_m5_end_minus_system_seconds=round(m5_delta, 1),
        difference_tick_minus_system_seconds=round(tick_delta, 1)
            if tick_delta is not None else None,
        status=status
    )


def main() -> int:
    from .adapters import MT5Adapter
    adapter = None
    try:
        adapter = MT5Adapter("GOLD")
        account = adapter.connect()
        check_demo_account(account, adapter.mt5)
        diagnosis = read_clock(
            adapter.mt5, symbol="GOLD", now=datetime.now(timezone.utc)
        )
        print(diagnosis.report(), flush=True)
        return 0
    except Exception as exc:
        # Only generate generic runtime error messages: no account, paths,
        # stack traces or provider internals printed.
        print(
            "DIAGNÓSTICO INDISPONÍVEL: "
            + str(exc).replace("\n", " ")[:180],
            flush=True,
        )
        return 1
    finally:
        if adapter is not None:
            adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
