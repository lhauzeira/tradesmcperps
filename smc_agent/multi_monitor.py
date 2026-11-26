"""Read-only multi-asset XM DEMO monitor. No order or Telegram submission.

Names come from ATIVOS_DEMO.txt; every asset gets independent status.
Uses market-specific display precision; never copies GOLD's risk contract.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import time
import webbrowser
from .monitor_local import capture, check_demo_account, _atomic_html, _fmt_price
from .journal import SignalJournal
from .lifecycle import PublishedSignal
from .readiness import ReadinessReport, evaluate_readiness
from .multi_timeframe import MultiTimeframeContext, observe_timeframes
from .mtf_research import classify_signal_context

SYMBOL_RE = re.compile(r"^[A-Za-z0-9._#-]{1,40}$")


@dataclass(frozen=True)
class MarketRow:
    symbol: str
    snapshot: object | None
    error: str | None
    readiness: ReadinessReport | None = None
    timeframes: MultiTimeframeContext | None = None


def read_symbol_list(path: str | Path) -> tuple[str, ...]:
    values, seen = [], set()
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        symbol = line.strip()
        if not symbol or symbol.startswith("#"):
            continue
        if not SYMBOL_RE.fullmatch(symbol):
            raise ValueError("Símbolo inválido na lista de ativos")
        if symbol.casefold() in seen:
            raise ValueError("Símbolo duplicado na lista")
        values.append(symbol)
        seen.add(symbol.casefold())
    if not 1 <= len(values) <= 12:
        raise ValueError("Adicione de 1 a 12 ativos, um por linha")
    return tuple(values)


def observe_one(mt5, symbol: str) -> MarketRow:
    from .adapters import MT5Adapter
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError("Símbolo inválido")
    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError("Símbolo não disponível no terminal da corretora")
        spec = mt5.symbol_info(symbol)
        digits = getattr(spec, "digits", None)
        if type(digits) is not int or not 0 <= digits <= 8:
            raise RuntimeError("Precisão decimal não confirmada no MT5")
        # MT5Adapter is a lightweight wrapper over the same initialized MT5
        # module; it does not connect/shutdown per symbol.
        adapter = MT5Adapter(symbol)
        snap = capture(adapter)
        snap = replace(snap, price_digits=digits)
        timeframes = observe_timeframes(adapter, snap)
        # A trading-mode flag alone does NOT prove today's broker session
        # or holiday calendar. v0.13 intentionally keeps that check false.
        readiness = evaluate_readiness(
            snap, spec,
            trade_mode_full=getattr(mt5, "SYMBOL_TRADE_MODE_FULL", None),
            session_verified=False,
        )
        return MarketRow(symbol, snap, None, readiness, timeframes)
    except Exception as exc:
        return MarketRow(symbol,None,str(exc).replace("\n"," ")[:160])


def render_market_table(rows: tuple[MarketRow, ...], now_iso: str) -> str:
    cards=[]
    for row in rows:
        sym=escape(row.symbol,quote=True)
        if row.error:
            cards.append(
                f'<section class="card"><h2>{sym}</h2>'
                f'<p class="error">Não avaliado: {escape(row.error,quote=True)}</p></section>'
            )
            continue
        s=row.snapshot
        fmt=lambda n: _fmt_price(n,s.price_digits)
        spread=(s.quote_ask-s.quote_bid
                if s.quote_bid is not None and s.quote_ask is not None else None)
        if s.fibonacci is None:
            fib="<p>Sem impulso confirmado compatível com o viés H1.</p>"
        else:
            f=s.fibonacci
            fib=(f'<p>Zona Fibonacci 61,8%–78,6%: '
                 f'<strong>{fmt(f.zone_low)} a {fmt(f.zone_high)}</strong></p>'
                 f'<p>50%: {fmt(f.price_50)} · 61,8%: {fmt(f.price_618)} · '
                 f'70,5%: {fmt(f.price_705)} · 78,6%: {fmt(f.price_786)}</p>'
                 f'<p>Estado: {escape(f.status,quote=True)}</p>')
        safety = row.readiness
        if safety is None:
            safety_html = "<p>Pré-execução ainda não avaliada. Ordens bloqueadas.</p>"
        else:
            codes = ", ".join(safety.block_codes) if safety.block_codes else "SEM_ALERTAS_DE_COTACAO"
            ratio = ("—" if safety.spread_to_m5_atr is None
                     else f"{safety.spread_to_m5_atr:.1%}")
            safety_html = (
                f'<p><strong>Portão de execução: {escape(safety.status)}</strong></p>'
                f'<p>Spread / ATR M5: {escape(ratio)} · '
                f'Condições pendentes: {escape(codes)}</p>'
                '<p>Este diagnóstico NÃO libera ordens. '
                'Sessões e feriados da corretora ainda não foram validados.</p>'
            )
        if row.timeframes is None:
            mtf_html = "<p>Leitura H4/H1/M30/M15/M5 ainda indisponível.</p>"
        else:
            summary = escape(row.timeframes.summary)
            frame_rows = []
            for frame in row.timeframes.frames:
                label = escape(frame.bias)
                state = escape(frame.state)
                closed_time = escape(frame.last_closed_utc or "—")
                detail = escape(frame.explanation) if frame.explanation else ""
                frame_rows.append(
                    f'<tr><td><b>{escape(frame.timeframe)}</b></td>'
                    f'<td>{label}</td><td>{closed_time}</td>'
                    f'<td>{state}{(" — " + detail) if detail else ""}</td></tr>'
                )
            mtf_html = (
                f'<h3>Estrutura em cinco períodos</h3><p>{summary}</p>'
                '<p class="note">Observacional: não altera o gatilho H1/M5 '
                'nem autoriza uma ordem. Ausência de dados não significa '
                'tendência neutra.</p>'
                '<div class="table-scroll"><table><thead><tr>'
                '<th>Período</th><th>Estrutura</th>'
                '<th>Último fechamento UTC</th><th>Validação</th>'
                '</tr></thead><tbody>' + ''.join(frame_rows)
                + '</tbody></table></div>'
            )
        signal = s.record
        research_tag = (
            classify_signal_context(signal.side, row.timeframes)
            if signal is not None and row.timeframes is not None else None
        )
        research_html = (
            f'<p>Confluência da hipótese SMC: <strong>{escape(research_tag.label)}</strong> '
            '(rótulo de pesquisa; NÃO é filtro nem previsão de lucratividade).</p>'
            if research_tag is not None else ""
        )
        alert=('<p>Sem novo setup SMC confirmado.</p>' if signal is None else
               f'<p class="warning">APENAS PESQUISA — '
               f'{escape("COMPRA" if signal.side=="buy" else "VENDA")}: '
               f'Entrada {fmt(signal.entry)}, Stop {fmt(signal.stop)}, '
               f'Alvo {fmt(signal.target)}. NÃO OPERAR.</p>')
        cards.append(
            f'<section class="card"><h2>{sym}: {escape(s.state)}</h2>'
            '<div class="grid">'
            f'<div>Bid<br><b>{fmt(s.quote_bid)}</b></div>'
            f'<div>Ask<br><b>{fmt(s.quote_ask)}</b></div>'
            f'<div>Spread (preço)<br><b>{fmt(spread)}</b></div>'
            f'<div>H1<br><b>{escape(s.h1_bias)}</b></div></div>'
            f'<p>M5 fechado UTC: {escape(s.last_closed_m5_utc or "—")}</p>'
            f'<p>Deslocamento observado: {escape(s.clock_offset_label)}</p>'
            f'{mtf_html}{fib}{research_html}{safety_html}{alert}</section>'
        )
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30"><meta name="viewport"
content="width=device-width,initial-scale=1">
<title>SMC Trading Agent — Multiativos XM DEMO</title><style>
body{{background:#101722;color:#eaf0fa;font-family:Segoe UI,Arial,sans-serif;margin:0}}
main{{max-width:1060px;margin:24px auto;padding:0 16px}}
.card{{background:#1c2b3c;border:1px solid #37495d;border-radius:14px;
margin:15px 0;padding:20px}}p{{color:#b5c9dd;line-height:1.6}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}}
.grid div{{padding:12px;background:#101d2a;border-radius:9px}}
b{{font-size:21px;color:#fff}}h1{{font-size:27px}}h2{{font-size:19px}}
.error{{color:#ffad9d}}.warning{{color:#ffdd98;background:#3b2e1e;padding:10px}}
h3{{font-size:17px;margin-top:22px}}.note{{font-size:13px}}
.table-scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #37495d;padding:9px}}
td b{{font-size:13px}}
</style></head><body><main>
<h1>SMC Trading Agent — Multiativos (DEMO)</h1>
<p>Monitor local de leitura, sem ordens. Fibonacci é observacional e NÃO
filtra os sinais ainda. Estratégia não validada financeiramente.</p>
<p>Diagnóstico pré-execução: cotação, spread/ATR e especificações de
cada ativo. A verificação de sessão/feriado está PENDENTE.
Nenhuma condição exibida equivale a autorização para enviar ordens.</p>
{''.join(cards)}
<p>Atualização UTC: {escape(now_iso)} · Ordens enviadas: 0 ·
Deslocamento horário provisório, sem validar histórico ou corretoras distintas.</p>
</main></body></html>"""


def monitor_many(*, root: Path | None = None, once: bool = False,
                 interval: int = 30) -> None:
    from .adapters import MT5Adapter
    if not 10 <= interval <= 3600:
        raise ValueError("Intervalo deve estar entre 10 e 3600 segundos")
    root=root or Path.cwd()
    symbols=read_symbol_list(root/"ATIVOS_DEMO.txt")
    output=root/"PAINEL_MULTI_DEMO.html"
    data=root/"monitoramento_privado"
    data.mkdir(parents=True,exist_ok=True)
    mt5=MT5Adapter(symbols[0]).mt5
    seen={}
    connected=False
    first=True
    try:
        while True:
            now=datetime.now(timezone.utc)
            try:
                if not connected:
                    if not mt5.initialize():
                        raise RuntimeError("Falha ao iniciar o MT5")
                    connected=True
                check_demo_account(mt5.account_info(),mt5)
                rows=tuple(observe_one(mt5,sym) for sym in symbols)
                for row in rows:
                    s=row.snapshot
                    if s is None: continue
                    if seen.get(row.symbol)!=s.last_closed_m5_utc:
                        seen[row.symbol]=s.last_closed_m5_utc
                        with (data/"analises_multi.jsonl").open("a",encoding="utf-8") as f:
                            f.write(json.dumps({
                                "symbol":row.symbol,"close_utc":s.last_closed_m5_utc,
                                "bias_h1":s.h1_bias,
                                "fibonacci":s.fibonacci.status if s.fibonacci else "SEM_SWING",
                                "signal":s.record is not None,
                                "pretrade_blocks":list(row.readiness.block_codes)
                                    if row.readiness is not None else ["SEM_VERIFICACAO"],
                                "multi_timeframe":row.timeframes.to_log()
                                    if row.timeframes is not None else None,
                                "mtf_signal_context":classify_signal_context(
                                    s.record.side, row.timeframes
                                ).to_log() if s.record is not None
                                and row.timeframes is not None else None,
                                "orders_sent":0
                            },ensure_ascii=False)+"\n")
                    if s.record is not None:
                        ev=s.record
                        signal=PublishedSignal(ev.event_id,s.server,row.symbol,
                                               ev.candle_closed_at,ev.side,
                                               ev.entry,ev.stop,ev.target)
                        with SignalJournal(data/"multi_sinais.sqlite3") as journal:
                            if journal.register(signal):
                                with (data/"multi_sinais.jsonl").open("a",encoding="utf-8") as f:
                                    f.write(json.dumps({
                                        "symbol":row.symbol,"event_id":ev.event_id,
                                        "side":ev.side,"entry":ev.entry,
                                        "stop":ev.stop,"target":ev.target,
                                        "time_utc":ev.candle_closed_at.isoformat(),
                                        "paper_only":True,"orders_sent":0,
                                        "multi_timeframe":row.timeframes.to_log()
                                            if row.timeframes is not None else None,
                                        "mtf_signal_context":classify_signal_context(
                                            ev.side, row.timeframes
                                        ).to_log() if row.timeframes is not None else None
                                    },ensure_ascii=False)+"\n")
                _atomic_html(output,render_market_table(rows,now.isoformat()))
                print(" | ".join(
                    f"{x.symbol}: {x.snapshot.state if x.snapshot else 'SEM DADOS'}"
                    for x in rows),flush=True)
            except Exception as exc:
                msg=str(exc).replace("\n"," ")[:160]
                rows=tuple(MarketRow(s,None,"MONITOR PAUSADO: "+msg) for s in symbols)
                _atomic_html(output,render_market_table(rows,now.isoformat()))
                print("[MONITOR PAUSADO] "+msg,flush=True)
                if connected:
                    mt5.shutdown()
                    connected=False
            if first:
                webbrowser.open(output.resolve().as_uri())
                first=False
            if once:break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Monitor encerrado, nenhuma ordem enviada.")
    finally:
        if connected:mt5.shutdown()


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="XM demo multiasset market reader")
    parser.add_argument("--uma-vez",action="store_true")
    parser.add_argument("--intervalo",type=int,default=30)
    args=parser.parse_args()
    monitor_many(once=args.uma_vez,interval=args.intervalo)
