# Native MetaTrader 5 tick CSV importer (v0.4)

This project has a strict importer for the **tab-separated tick export** from
MetaTrader 5's Symbols / Ticks UI. Supported columns are:

    <DATE> <TIME> <BID> <ASK> <LAST> <VOLUME> <FLAGS>

The original export does NOT embed its instrument or server timezone. A file
name such as GOLD does not automatically prove that quotes are identical to
a third-party XAUUSD signal or a futures/perpetual contract.

## Privacy

Keep actual user tick exports outside GitHub. The original historical series
received in private conversation is NOT included in this public repository.
The code and tests contain only fabricated quotes.

## Examine the input without inventing a timezone

    from smc_agent.mt5_export import inspect_mt5_export
    result = inspect_mt5_export("private/path/to/MT5_ticks.csv")
    print(result)

The inspection reports coverage and incomplete Bid/Ask quote updates, plus
date/time gaps. It does not claim an outcome or infer UTC offset.

## Only after verifying the broker's historical time offset

Example API: these offsets are placeholders; DO NOT reuse without checking
the exact broker server and historical date.

    from datetime import datetime, timezone
    from smc_agent.mt5_export import load_mt5_quote_export
    history = load_mt5_quote_export(
        "private/path/to/MT5_ticks.csv",
        venue="BROKER_AND_SERVER_VERIFIED",
        symbol="BROKER_NATIVE_SYMBOL",
        verified_utc_offset_minutes=0,
        timeframe_seconds=300,
        as_of=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )

The method fails if the historical offset is absent. It excludes update-only
rows without both Bid and Ask rather than inventing missing quotes. Therefore
aggregated highs/lows may **miss quote-side-only moves** and the series must
not be used as evidence of realized returns until full completeness, market
session rules, trade types and spreads are validated.

The final unfinished candle is discarded. Time gaps are not interpolated.

## Historical signal comparison

- Telegram publication timestamp is distinct from a **future timestamp printed
  inside the alert**. Never use a future-printed "signal timestamp" to suggest
  earlier knowledge or a confirmed entry.
- Only compare the same broker/instrument and separately establish the
  historical server UTC offset including seasonal shifts.
- Both Bid and Ask must be interpreted in the order type's own quote convention.
- A touched TP does not mean an order was submitted, filled, or profitable.
- Actual latency, partial fills, trading fees, swap/funding, slippage and the
  prop-firm risk rules are not modeled.

The original downloaded CSV and any generated quotes must remain private.
