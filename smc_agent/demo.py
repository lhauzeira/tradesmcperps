"""Demonstração offline sem credenciais, sem ordens e sem promessa de ganhos."""
import json
from datetime import datetime, timezone, timedelta
from .engine import Candle, confirmed_pivots, atr_at, macro_bias
from .risk import allowed_loss


def report():
    epoch = datetime(2026, 1, 5, tzinfo=timezone.utc)
    bars = [Candle(epoch + timedelta(minutes=5*i), 100+i*.05, 100+i*.05+.3,
                   100+i*.05-.3, 100+i*.05, 100) for i in range(60)]
    pivots = confirmed_pivots(bars)
    return {
        "project": "SMC Trading Agent",
        "status": "research prototype",
        "dataset": "synthetic_offline",
        "uses_real_market_data": False,
        "automated_execution": False,
        "orders_sent": 0,
        "bars_processed": len(bars),
        "confirmed_pivots": len(pivots),
        "atr_last": round(atr_at(bars, len(bars)-1), 6),
        "macro_bias": macro_bias(bars),
        "minimum_lot_risk_budget_usd_on_100_equity": allowed_loss(100),
        "profitability_claim": "none",
        "next": "backtest with market feeds; validate native platform data and sandbox connectivity",
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, ensure_ascii=False))
