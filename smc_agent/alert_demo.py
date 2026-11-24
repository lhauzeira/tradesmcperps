"""Static synthetic sample demonstrating message formatting without sending it."""
from datetime import datetime, timezone
from .engine import OrderBlock, Signal
from .alerts import from_engine, telegram_preview, AlertBuffer


def main():
    ob = OrderBlock("buy", low=99.0, high=101.0, candle_index=30, bos_index=33)
    # These are fabricated teaching values, NOT observed prices or a recommendation.
    sample = Signal("buy", entry=102.0, stop=100.0, target=107.0,
                    rr=2.5, ob=ob,
                    reason="Synthetic BOS / OB / 50% mitigation example")
    closed_at = datetime(2026, 1, 5, 15, 5, tzinfo=timezone.utc)
    record = from_engine(sample, symbol="TEST_SYNTH", timeframe="M5",
                         candle_closed_at=closed_at)
    gate = AlertBuffer()
    print(telegram_preview(record))
    print("\nTest of duplicate prevention:",
          "first accepted" if gate.enqueue(record) else "rejected",
          ", second rejected" if not gate.enqueue(record) else ", second accepted")


if __name__ == "__main__":
    main()
