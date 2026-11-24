"""Reproducible demonstration of level-touch auditing. NO REAL MARKET DATA."""
import json
from datetime import datetime, timedelta, timezone

from .journal import SignalJournal
from .lifecycle import ObservedBar, PublishedSignal, observe


def demo() -> dict:
    utc = timezone.utc
    base = datetime(2026, 6, 22, 12, 0, tzinfo=utc)
    plan = PublishedSignal(
        signal_id="synthetic-only-001", venue="SYNTHETIC_ONLY",
        symbol="TEST_XAUUSD", published_at=base+timedelta(minutes=2),
        side="buy", entry=100.0, stop=95.0, target=110.0,
    )
    candles = [
        # A candle with levels before signal publication must not be used.
        ObservedBar(base, base+timedelta(minutes=5), 100, 115, 94, 105),
        # Fully after publication; entry-level was touched.
        ObservedBar(base+timedelta(minutes=5), base+timedelta(minutes=10),
                    101, 103, 99, 101),
        # Later bar touches the target level. No fill is inferred.
        ObservedBar(base+timedelta(minutes=10), base+timedelta(minutes=15),
                    101, 111, 100, 110),
    ]
    result = observe(
        plan, candles, feed_venue="SYNTHETIC_ONLY", feed_symbol="TEST_XAUUSD",
        as_of=base+timedelta(minutes=15),
    )
    with SignalJournal(":memory:") as journal:
        created = journal.register(plan)
        duplicate_ignored = not journal.register(plan)
        journal.append(result, as_of=base+timedelta(minutes=15))
        journal_snapshot = journal.counts(plan.signal_id)

    return {
        "demonstration": "synthetic_only",
        "not_a_real_signal": True,
        "automated_orders_sent": 0,
        "verified_broker_fills": 0,
        "verified_realized_profit": False,
        "observed_price_status": result.status,
        "post_publication_closed_candles_analyzed": result.bars_examined,
        "journal_registered": created,
        "duplicate_record_ignored": duplicate_ignored,
        "journal_counts": journal_snapshot,
        "interpretation": "OHLC price touches, not proof of execution or performance",
    }


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, ensure_ascii=False))
