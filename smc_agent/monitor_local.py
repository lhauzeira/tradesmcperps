"""LOCAL-ONLY XM demo GOLD research monitor (never opens brokerage orders).

Uses the EXISTING experimental SMC engine on genuinely closed M5/H1
candles from a locally running MetaTrader 5 terminal. The account is
re-checked every scan; real/unknown accounts fail closed.

NO Telegram sending, broker orders, remote web server, external APIs,
profit claims or credentials. The browser opens a local static HTML file.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import time
import webbrowser

from .alerts import SignalRecord, from_engine
from .engine import analyze, macro_bias, atr_at
from .fibonacci import FibonacciObservation, observe_fibonacci
from .journal import SignalJournal
from .lifecycle import PublishedSignal
from .live_clock import reconcile_live_clock

EXPECTED_SERVER = "XMGlobal-MT5 5"
M5_SECONDS = 300
MAX_AGE_SECONDS = 900


def check_demo_account(account, mt5, *, expected_server: str = EXPECTED_SERVER):
    """Never scan or generate a signal while account type is not verified demo."""
    expected_trade_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    if expected_trade_mode is None:
        raise RuntimeError("MT5 não informa o código de conta demo. Leitura bloqueada.")
    if account is None or getattr(account, "trade_mode", None) != expected_trade_mode:
        raise RuntimeError("BLOQUEADO: somente conta DEMO é permitida.")
    if getattr(account, "server", None) != expected_server:
        raise RuntimeError("Servidor diferente do XMGlobal-MT5 5 esperado. Leitura bloqueada.")


@dataclass(frozen=True)
class MonitorSnapshot:
    generated_utc: str
    symbol: str
    server: str
    connected_to_demo: bool
    state: str
    last_closed_m5_utc: str | None = None
    last_closed_h1_utc: str | None = None
    last_m5_bid_close: float | None = None
    h1_bias: str = "NÃO AVALIADO"
    quote_bid: float | None = None
    quote_ask: float | None = None
    quote_time_utc: str | None = None
    age_last_m5_seconds: float | None = None
    record: SignalRecord | None = None
    clock_offset_label: str = "NÃO VERIFICADO"
    fibonacci: FibonacciObservation | None = None
    price_digits: int = 2
    m5_atr_price: float | None = None
    warning: str = "Somente pesquisa. Não operar com esses sinais."


def capture(adapter, *, now: datetime | None = None,
            expected_server: str = EXPECTED_SERVER) -> MonitorSnapshot:
    """Read closed candles; measure PC UTC AFTER the terminal tick read.

    Tests may inject an explicit datetime; production takes the time when
    the market snapshot is already available, to avoid false +seconds
    from potentially slow MT5.initialize() and history fetches.
    """
    if now is not None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Relógio de verificação deve ter fuso horário")
        now = now.astimezone(timezone.utc)
    check_demo_account(adapter.mt5.account_info(), adapter.mt5,
                       expected_server=expected_server)

    m5 = adapter.bars("M5", count=240)
    h1 = adapter.bars("H1", count=160)
    if len(m5) < 50 or len(h1) < 40:
        raise RuntimeError("Histórico fechado insuficiente. Abra GOLD M5/H1 no MT5.")
    # The live demo terminal may return broker-clock-like raw timestamp
    # integers; screenshot 2026-11-26 showed tick +02:00 vs PC UTC.
    # Never force UTC+2 here: infer a candidate anew EACH scan and validate
    # fresh tick + independently closed M5/H1. Historical June not inferred.
    get_tick = getattr(adapter.mt5, "symbol_info_tick", None)
    if not callable(get_tick):
        raise RuntimeError("MT5 não forneceu leitura de tick GOLD; sem sinal")
    tick = get_tick(adapter.symbol)
    if tick is None:
        raise RuntimeError("Último tick GOLD indisponível; sem sinal")
    raw_tick_time = getattr(tick, "time", None)
    raw_msc = getattr(tick, "time_msc", None)
    if isinstance(raw_msc, (int, float)) and raw_msc > 0:
        # If both timestamp fields exist, they must refer to the same
        # instant; do not automatically privilege a contradictory field.
        if not isinstance(raw_tick_time, (int, float)) or abs(raw_msc/1000 - raw_tick_time) > 2:
            raise RuntimeError("Divergência entre time e time_msc do tick GOLD")
        raw_tick_time = raw_msc / 1000

    if now is None:
        now = datetime.now(timezone.utc)
    clock = reconcile_live_clock(
        now=now, raw_tick_seconds=raw_tick_time,
        raw_m5_open=m5[-1].time, raw_h1_open=h1[-1].time,
    )
    m5_close = clock.m5_closed_utc
    h1_close = clock.h1_closed_utc
    age = clock.m5_age_seconds

    bid = ask = None
    qbid, qask = getattr(tick, "bid", None), getattr(tick, "ask", None)
    if (isinstance(qbid, (int, float)) and isinstance(qask, (int, float))
            and 0 < qbid <= qask):
        bid, ask = float(qbid), float(qask)

    # These candles are only used for their shapes and chronological
    # ordering in the SMC engine; older bar timezones are NOT rewritten
    # by the live observed offset (seasonal transitions may exist).
    signal = analyze(h1, m5)
    state = "SINAL DE PESQUISA — NÃO OPERAR" if signal else "AGUARDANDO SETUP SMC"

    bias = macro_bias(h1)
    bias_text = "ALTA" if bias > 0 else "BAIXA" if bias < 0 else "NEUTRO"
    fib = observe_fibonacci(m5, side="buy" if bias > 0 else "sell") if bias != 0 else None
    # The MT5 symbol itself determines quote precision. No FX/crypto
    # instrument is formatted using GOLD's hard-coded 2 digits.
    info_fn = getattr(adapter.mt5, "symbol_info", None)
    digits = 2
    if callable(info_fn):
        info = info_fn(adapter.symbol)
        raw_digits = getattr(info, "digits", None) if info is not None else None
        if isinstance(raw_digits, int) and not isinstance(raw_digits, bool) and 0 <= raw_digits <= 8:
            digits = raw_digits
    record = (from_engine(signal, symbol=adapter.symbol, timeframe="M5",
                          candle_closed_at=m5_close,
                          source="xm-demo-smc-v10-observed-live-clock")
              if signal is not None else None)

    return MonitorSnapshot(
        generated_utc=now.isoformat(), symbol=adapter.symbol,
        server=expected_server, connected_to_demo=True, state=state,
        last_closed_m5_utc=m5_close.isoformat(),
        last_closed_h1_utc=h1_close.isoformat(),
        last_m5_bid_close=m5[-1].close, h1_bias=bias_text,
        quote_bid=bid, quote_ask=ask, quote_time_utc=clock.tick_utc.isoformat(),
        age_last_m5_seconds=round(age, 1), record=record,
        clock_offset_label=clock.offset_label,
        fibonacci=fib, price_digits=digits,
        m5_atr_price=atr_at(m5, len(m5) - 1),
        warning="Horário AO VIVO reconciliado com tick, M5 e H1: "
                "não prova fuso histórico. SMC experimental, sem ordens, "
                "custos, sessões históricas ou validação de resultado."
    )


def _fmt_price(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    if not isinstance(digits, int) or isinstance(digits, bool) or not 0 <= digits <= 8:
        raise ValueError("Invalid symbol price precision")
    return f"{value:,.{digits}f}"


def _plain(value) -> str:
    return escape(str(value), quote=True)


def render_html(snapshot: MonitorSnapshot, *, last_event: dict | None = None) -> str:
    """Standalone local HTML; all user/feed text escaped, no remote content."""
    event = last_event
    if snapshot.record:
        rec = snapshot.record
        event = {
            "side": rec.side, "entry": rec.entry, "stop": rec.stop,
            "target": rec.target, "rr": rec.rr,
            "close": rec.candle_closed_at.isoformat(),
            "reason": rec.reason, "id": rec.event_id,
        }
    signal_section = (
        "<p>Nenhum sinal SMC confirmado nesta atualização. Isso é normal; "
        "não tente antecipar entradas.</p>"
    )
    if event:
        dir_text = "COMPRA" if event["side"] == "buy" else "VENDA"
        signal_section = (
            f"<p><strong>Último sinal experimental:</strong> {_plain(dir_text)}</p>"
            f"<div class='columns'><div>Entrada teórica<br><b>{_fmt_price(event['entry'], snapshot.price_digits)}</b></div>"
            f"<div>Stop teórico<br><b>{_fmt_price(event['stop'], snapshot.price_digits)}</b></div>"
            f"<div>Alvo teórico<br><b>{_fmt_price(event['target'], snapshot.price_digits)}</b></div></div>"
            f"<p>Fechamento do candle (UTC): {_plain(event['close'])}</p>"
            f"<p>Motivo: {_plain(event['reason'])}</p>"
            "<p class='caution'>Este é um alerta de pesquisa, não ordem executada "
            "nem sinal de eficácia comprovada.</p>"
        )
    spread = None
    if snapshot.quote_bid is not None and snapshot.quote_ask is not None:
        spread = snapshot.quote_ask - snapshot.quote_bid
    status_badge = _plain(snapshot.state)
    if snapshot.fibonacci is None:
        fib_section = "<p>Sem impulso confirmado compatível com o viés H1.</p>"
    else:
        fb = snapshot.fibonacci
        fmt = lambda value: _fmt_price(value, snapshot.price_digits)
        fib_section = (
            "<p>Fibonacci experimental: " + _plain(fb.side.upper()) + "</p>"
            f"<p>50%: <b>{fmt(fb.price_50)}</b> · "
            f"61,8%: <b>{fmt(fb.price_618)}</b> · "
            f"70,5%: <b>{fmt(fb.price_705)}</b> · "
            f"78,6%: <b>{fmt(fb.price_786)}</b></p>"
            f"<p>Zona OTE: {fmt(fb.zone_low)}–{fmt(fb.zone_high)}"
            f" · Estado: {_plain(fb.status)}</p>"
        )
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC Agent — XM GOLD Demo</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#0e1622;color:#f3f5fa;
margin:0;line-height:1.5}}main{{max-width:920px;margin:auto;padding:30px 18px}}
header{{display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between;align-items:center}}
.card{{background:#182434;border:1px solid #314057;border-radius:14px;padding:19px;margin:16px 0}}
h1{{font-size:27px;margin:0}}h2{{font-size:19px;margin:2px 0 12px}}
p{{color:#c9d5e3}}small{{color:#92a6bd}}.badge{{background:#233449;padding:10px;
border-radius:10px;font-weight:600}}.columns{{display:grid;grid-template-columns:
repeat(auto-fit,minmax(165px,1fr));gap:12px}}.columns>div{{background:#111c29;
padding:13px;border-radius:10px;color:#a8bdd1}}.columns b{{font-size:23px;color:#fff}}
.caution{{background:#332618;color:#ffdaa3;padding:12px;border-radius:8px}}
a{{color:#a9d2ff}}.footer{{font-size:13px;color:#90a5b7}}
</style></head><body><main>
<header><div><h1>SMC Trading Agent</h1><small>Monitor local • XM GOLD • conta DEMO</small></div>
<span class="badge">{status_badge}</span></header>
<div class="card"><h2>Mercado</h2><div class="columns">
<div>Bid atual<br><b>{_fmt_price(snapshot.quote_bid, snapshot.price_digits)}</b></div>
<div>Ask atual<br><b>{_fmt_price(snapshot.quote_ask, snapshot.price_digits)}</b></div>
<div>Spread atual em preço<br><b>{_fmt_price(spread, snapshot.price_digits)}</b></div>
<div>Viés H1<br><b>{_plain(snapshot.h1_bias)}</b></div>
</div><p>Último candle M5 fechado: {_plain(snapshot.last_closed_m5_utc or '—')}<br>
Fechamento Bid M5: {_fmt_price(snapshot.last_m5_bid_close, snapshot.price_digits)}<br>
Última cotação reportada: {_plain(snapshot.quote_time_utc or 'indisponível')}</p></div>
<div class="card"><h2>Horários do MT5 — apenas pesquisa ao vivo</h2>
<p>Diferença observada nesta leitura: <b>{_plain(snapshot.clock_offset_label)}</b></p>
<p>Isso não prova o fuso de junho nem confirma horários históricos. Cada leitura
é validada novamente com tick, M5 e H1. Se houver divergência, o monitor pausa.
Não altere o relógio do computador.</p></div>
<div class="card"><h2>Fibonacci — confluência em observação</h2>
{fib_section}
<p>OTE apenas como contexto, não como filtro obrigatório dos sinais.
O valor estatístico dessa confluência ainda precisa ser testado.</p></div>
<div class="card"><h2>Análise SMC (experimental)</h2>{signal_section}</div>
<div class="card"><h2>Segurança e funcionamento</h2>
<p>Somente dados de mercado e análises locais. Ordens enviadas: <b>0</b>.
A conexão só funciona com conta demonstrativa no servidor autorizado.</p>
<p>Sem mensagens ao Telegram, sem senhas armazenadas, sem acesso remoto e
sem promessas de lucratividade. Esta página atualiza a cada 30 segundos.</p>
</div><p class="footer">Atualização UTC: {_plain(snapshot.generated_utc)} ·
Servidor: {_plain(snapshot.server)} · Instrumento: {_plain(snapshot.symbol)}
· Arquivo local: nenhum serviço web externo.</p></main></body></html>"""
    return html


def _atomic_html(path: Path, contents: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(contents, encoding="utf-8")
    temp.replace(path)


def _last_signal_from_log(path: Path) -> dict | None:
    if not path.exists():
        return None
    # Avoid exposing any financial/account data; only static signal plans
    # are included, with a capped read of an existing user-local file.
    if path.stat().st_size > 5_000_000:
        return None
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return last


def monitor(*, symbol: str = "GOLD", interval: int = 30, once: bool = False,
            folder: Path | None = None, expected_server: str = EXPECTED_SERVER):
    from .adapters import MT5Adapter
    if symbol != "GOLD":
        raise ValueError("Este monitor experimental só aceita GOLD da XM demo")
    if interval < 10 or interval > 3600:
        raise ValueError("Intervalo deve ficar entre 10 e 3600 segundos")
    root = folder or Path.cwd()
    data = root / "monitoramento_privado"
    data.mkdir(parents=True, exist_ok=True)
    page = root / "MONITOR_LOCAL_DEMO.html"
    signals_file = data / "sinais.jsonl"
    candles_file = data / "analises_m5.jsonl"
    last_event = _last_signal_from_log(signals_file)
    last_bar = None
    adapter = None
    browser_opened = False

    try:
        while True:
            now = datetime.now(timezone.utc)
            try:
                if adapter is None:
                    adapter = MT5Adapter(symbol)
                    account = adapter.connect()
                    check_demo_account(account, adapter.mt5, expected_server=expected_server)
                snap = capture(adapter, expected_server=expected_server)
                if snap.last_closed_m5_utc != last_bar:
                    last_bar = snap.last_closed_m5_utc
                    record = {
                        "event": "M5_CLOSED_ANALYSIS_ONLY", "symbol": symbol,
                        "candle_close_utc": last_bar, "h1_bias": snap.h1_bias,
                        "engine_signal_present": snap.record is not None,
                    }
                    with candles_file.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")

                if snap.record is not None:
                    rec = snap.record
                    proposal = PublishedSignal(
                        rec.event_id, expected_server, rec.symbol, rec.candle_closed_at,
                        rec.side, rec.entry, rec.stop, rec.target)
                    with SignalJournal(data / "sinais.sqlite3") as journal:
                        if journal.register(proposal):
                            last_event = {
                                "id": rec.event_id, "side": rec.side,
                                "entry": rec.entry, "stop": rec.stop,
                                "target": rec.target, "rr": rec.rr,
                                "close": rec.candle_closed_at.isoformat(),
                                "reason": rec.reason,
                            }
                            with signals_file.open("a", encoding="utf-8") as stream:
                                stream.write(json.dumps(last_event, ensure_ascii=False) + "\n")
                _atomic_html(page, render_html(snap, last_event=last_event))
                print(f"[{now.strftime('%H:%M:%S')} UTC] {snap.state} / "
                      f"M5: {snap.last_closed_m5_utc} / H1: {snap.h1_bias}",
                      flush=True)
            except Exception as exc:
                # Security: no account number, credentials, token, or mt5
                # terminal settings are logged in the browser.
                msg = str(exc).replace("\n", " ")[:250]
                print(f"[MONITOR PAUSADO] {msg}", flush=True)
                stopped = MonitorSnapshot(
                    generated_utc=now.isoformat(), symbol=symbol,
                    server=expected_server, connected_to_demo=False,
                    state="MONITOR PAUSADO — VERIFICAR MT5",
                    warning=msg,
                )
                html = render_html(stopped).replace(
                    '<div class="card"><h2>Segurança e funcionamento</h2>',
                    f'<div class="card"><h2>Diagnóstico</h2><p>{_plain(msg)}</p></div>'
                    '<div class="card"><h2>Segurança e funcionamento</h2>',
                )
                _atomic_html(page, html)
                if adapter is not None:
                    try:
                        adapter.close()
                    except Exception:
                        pass
                    adapter = None
            if not browser_opened:
                webbrowser.open(page.resolve().as_uri())
                browser_opened = True
            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Monitor encerrado pelo usuário. Nenhuma ordem foi enviada.")
    finally:
        if adapter is not None:
            adapter.close()


def main():
    parser = argparse.ArgumentParser(description="Local XM MT5 DEMO SMC monitor, sem ordens")
    parser.add_argument("--uma-vez", action="store_true", help="Ler uma vez e sair")
    parser.add_argument("--intervalo", type=int, default=30, help="Segundos entre leituras")
    args = parser.parse_args()
    monitor(interval=args.intervalo, once=args.uma_vez)


if __name__ == "__main__":
    main()
