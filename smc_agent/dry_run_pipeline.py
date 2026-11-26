"""One-piece rehearsal: native-style broker preflight + recovery journal.

All quotes, equity, positions and MT5 API responses here are invented.
No MetaTrader5 import, no internet, no brokerage login, NO order_send.

Purpose: verify that a future auto-trading pipeline can recognize a
preflight block and quarantine uncertain intent across process restart.
It is NOT a real MT5 fill, broker backtest or profit evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from .demo_preflight import DemoOrderHypothesis, estimate_demo_order
from .order_intent_journal import ResearchOrderIntent, ResearchIntentJournal


class FakeDemoBroker:
    ACCOUNT_TRADE_MODE_DEMO = 0
    SYMBOL_TRADE_MODE_FULL = 4
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1

    def __init__(self):
        self.actions = []
        self.account = SimpleNamespace(
            server="XMGlobal-MT5 5", trade_mode=0, currency="USD",
            equity=10000.0, margin_free=8000.0,
            trade_allowed=True, trade_expert=True
        )
        self.spec = SimpleNamespace(
            volume_min=0.01, volume_max=50.0, volume_step=0.01,
            trade_tick_size=0.01, point=0.01, trade_stops_level=20,
            trade_mode=4,
        )

    def account_info(self):
        self.actions.append("account_info")
        return self.account

    def positions_get(self):
        self.actions.append("positions_get")
        return ()

    def orders_get(self):
        self.actions.append("orders_get")
        return ()

    def symbol_select(self, symbol, selected):
        self.actions.append("symbol_select")
        return symbol == "GOLD" and selected is True

    def symbol_info(self, symbol):
        self.actions.append("symbol_info")
        return self.spec

    def symbol_info_tick(self, symbol):
        self.actions.append("symbol_info_tick")
        return SimpleNamespace(bid=100.0, ask=100.2)

    def order_calc_profit(self, side, symbol, lots, entry, stop):
        self.actions.append("order_calc_profit")
        # EXACTLY a fictitious fill value, not an XM currency conversion.
        return (stop-entry)*lots*100 if side == 0 else (entry-stop)*lots*100

    def order_calc_margin(self, side, symbol, lots, entry):
        self.actions.append("order_calc_margin")
        return 1000*lots

    def order_send(self, *_args, **_kwargs):
        raise AssertionError("NO ORDER: fake broker cannot send")

    def order_check(self, *_args, **_kwargs):
        raise AssertionError("NO ORDER: fake broker cannot check")


def rehearse_demo_preflight_recovery() -> dict[str, object]:
    now = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
    mt5 = FakeDemoBroker()
    evidence = SimpleNamespace(
        symbol="GOLD", connected_to_demo=True,
        generated_utc=(now-timedelta(seconds=1)).isoformat(),
        quote_time_utc=(now-timedelta(seconds=2)).isoformat(),
        quote_bid=100.0, quote_ask=100.2,
        clock_offset_label="UTC+02:00 (observado agora, provisório)",
    )
    planned = DemoOrderHypothesis(
        signal_id="FICTICIO-001",symbol="GOLD",side="buy",
        volume=Decimal("0.1"),stop=Decimal("99"),target=Decimal("102.5")
    )
    report = estimate_demo_order(mt5,planned,now=now,
                                 market_evidence=evidence)
    if report.can_submit_orders or "EXECUCAO_DE_ORDENS_DESABILITADA" not in report.blockers:
        raise AssertionError("Order gate failed to block")
    if "COTACAO_RECENTE_NAO_CONCILIADA" in report.blockers:
        raise AssertionError("Synthetic live-clock evidence was not recognized")
    if report.theoretical_loss_account_currency is None:
        raise AssertionError("Synthetic native risk calculation failed")

    with TemporaryDirectory() as folder:
        database=Path(folder)/"research_only.sqlite3"
        intent=ResearchOrderIntent(
            event_id=planned.signal_id,
            venue="XMGlobal-MT5 5 (DEMO-RESEARCH)",
            symbol=planned.symbol,side=planned.side,
            volume=str(planned.volume),stop=str(planned.stop),
            target=str(planned.target),
        )
        with ResearchIntentJournal(database) as journal:
            if not journal.register(intent,at=now):
                raise AssertionError("New signal was not registered")
            journal.transition(
                intent.event_id,"SIMULATED_SEND_UNKNOWN",
                at=now+timedelta(seconds=1),
                note="Este é somente um ensaio; nenhum envio foi realizado"
            )
        with ResearchIntentJournal(database) as restarted:
            quarantined=restarted.quarantine_unresolved_after_restart(
                at=now+timedelta(seconds=2)
            )
            deduped = not restarted.register(
                intent,at=now+timedelta(seconds=3)
            )
            state = restarted.state(intent.event_id)
    if quarantined != 1 or not deduped or state != "RECONCILE_REQUIRED":
        raise AssertionError("Crash recovery failed to quarantine intent")
    if "order_send" in mt5.actions or "order_check" in mt5.actions:
        raise AssertionError("Unexpected broker order function used")
    return {
        "source": "FICTICIOUS_MARKET_AND_ACCOUNT",
        "risk_account_currency": report.account_currency,
        "planned_loss_estimate": str(report.theoretical_loss_account_currency),
        "planned_margin_estimate": str(report.estimated_margin_account_currency),
        "broker_blockers": list(report.blockers),
        "intent_after_restart": state,
        "duplicate_prevented": deduped,
        "orders_sent": 0,
    }


def main() -> None:
    result=rehearse_demo_preflight_recovery()
    print("ENSAIO INTEGRADO — PRE-FLIGHT E REINICIO / DADOS 100% FICTICIOS")
    print(f"Estimativa de perda ate stop: {result['planned_loss_estimate']} {result['risk_account_currency']}")
    print(f"Estimativa de margem: {result['planned_margin_estimate']} {result['risk_account_currency']}")
    print(f"Bloqueios intencionais: {', '.join(result['broker_blockers'])}")
    print(f"Estado apos reinicio: {result['intent_after_restart']}")
    print(f"Duplicidade impedida: {result['duplicate_prevented']}")
    print("SEM CONEXAO MT5, ZERO ORDENS ENVIADAS. Lucro nao demonstrado.")


if __name__ == "__main__":
    main()
