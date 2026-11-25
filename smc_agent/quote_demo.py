"""Offline bid/ask inspection demonstration using FABRICATED quotes, no network."""
from datetime import datetime, timezone
import json
from pathlib import Path

from .lifecycle import PublishedSignal
from .quotes import load_quote_csv, observe_quotes


def demo():
    filename = Path(__file__).resolve().parents[1] / "examples" / "synthetic_bidask_v04.csv"
    history = load_quote_csv(filename)
    if (history.venue, history.symbol, history.origin) != (
        "SYNTHETIC_ONLY", "TEST_XAUUSD", "fabricated_for_tests"
    ):
        raise RuntimeError("Demo must never be run against live/proprietary data")
    signal = PublishedSignal(
        signal_id="example-only-quote-001", venue=history.venue, symbol=history.symbol,
        published_at=datetime(2026, 6, 22, 12, 2, tzinfo=timezone.utc),
        side="buy", entry=100, stop=95, target=110,
    )
    result = observe_quotes(
        signal, history, as_of=history.bars[-1].closed_at,
        quote_policy="buy_ask_sell_bid", max_open_spread_pct=1.0,
    )
    return {
        "dataset": "SYNTHETIC_NOT_MARKET_DATA",
        "venue": history.venue,
        "symbol": history.symbol,
        "bars_in_file": len(history.bars),
        "post_publication_bars_examined": result.bars_examined,
        "quote_convention": "buy_ask_sell_bid",
        "price_level_observation": result.status,
        "proven_market_outcome": False,
        "verified_broker_fills": 0,
        "realized_PnL": None,
        "orders_sent": 0,
    }


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2))
