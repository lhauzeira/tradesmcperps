"""Reproducible, clearly fabricated GOLD paper replay; no MT5 connection."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

from .lifecycle import PublishedSignal
from .quotes import QuoteBar, QuoteHistory
from .paper import (
    PaperAssumptions, TradingSessions, SessionWindow, replay_market_next_open
)
from .xm_gold_risk import XM_GOLD_DEMO_SNAPSHOT


def demo() -> dict:
    base = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    contract = replace(
        XM_GOLD_DEMO_SNAPSHOT, venue="SYNTHETIC_ONLY", symbol="TEST_GOLD"
    )
    signal = PublishedSignal(
        signal_id="fabricated-market-next-open", venue=contract.venue,
        symbol=contract.symbol, published_at=base+timedelta(minutes=2),
        side="buy", entry=4000.20, stop=3999.00, target=4002.00
    )

    def bar(minute, o, h, l, c):
        start = base+timedelta(minutes=minute)
        return QuoteBar(
            start, start+timedelta(minutes=5),
            o, h, l, c,
            o+.2, h+.2, l+.2, c+.2
        )

    history = QuoteHistory(
        contract.venue, contract.symbol, "FABRICATED_NO_REAL_MARKET_TICKS",
        (bar(5,4000,4000.5,3999.8,4000.1),
         bar(10,4000.1,4003.0,3999.9,4002.5))
    )
    model = PaperAssumptions(
        risk_budget_usd=Decimal("5"),
        extra_loss_reserve_usd=Decimal("1"),
        commission_roundtrip_usd_per_lot=Decimal("10"),
        slippage_each_side_price=Decimal(".02"),
        max_entry_drift_price=Decimal(".50"),
        max_open_spread_pct=Decimal(".10"),
    )
    synthetic_calendar = TradingSessions(
        verified_server_utc_offset_minutes=0,
        weekdays={0: (SessionWindow(0,1439),)}
    )
    observed = replay_market_next_open(
        signal, history, sessions=synthetic_calendar, assumptions=model,
        as_of=base+timedelta(minutes=15), contract=contract
    )
    missing_calendar = replay_market_next_open(
        signal, history,
        sessions=TradingSessions(
            verified_server_utc_offset_minutes=None,
            weekdays={}),
        assumptions=model, as_of=base+timedelta(minutes=15), contract=contract
    )
    return {
        "data": "SYNTHETIC_QUOTES_ONLY",
        "calendar": "SYNTHETIC_ASSUMED_UTC_MONDAY_ONLY",
        "modeled_status": observed.status,
        "modeled_lots": str(observed.paper_lots),
        "modeled_net_usd": str(observed.modeled_net_usd),
        "modeled_roundtrip_commission_usd": str(observed.modeled_fees_usd),
        "model_assumes": "next_quote_bar_open, explicit spread, cost, slippage",
        "without_verified_calendar": missing_calendar.status,
        "realized_profit": None,
        "real_market_performance": "NOT_MEASURED",
        "verified_broker_fills": 0,
        "orders_sent": 0,
    }


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, ensure_ascii=False))
