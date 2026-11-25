# Bid/ask quote research — v0.4 draft

**This is an offline input/observation prototype, not live market connectivity.**
No keys, accounts, trading or Telegram messaging are involved.

## Why split bid and ask?

An MT5 bar fetched via the normal rates API does **not** prove the historical
Ask high/low. An Ask series cannot be reconstructed reliably by adding one fixed
spread to every historical Bid price. MFP perpetual marks, last prices, bid/ask
quotes, and CME futures are different instruments and feeds.

For an explicitly declared *marketable-quote proxy*:
- Long entry is compared with **Ask** range; stop/target with **Bid** range.
- Short entry is compared with **Bid** range; stop/target with **Ask** range.

These represent **price-level touches only**, not order fills. For
stop-market/limit/stop-limit orders, execution rules, touch semantics,
liquidity and queue modeling must be explicitly defined later.

## Run local demo (fully synthetic)

From the repository root:

    python -m smc_agent.quote_demo
    python -m unittest discover -s tests -v

The demo reads:

    examples/synthetic_bidask_v04.csv

All timestamps, instruments and quote values in the file are **fabricated**.
The program intentionally labels its output SYNTHETIC_NOT_MARKET_DATA,
sets PnL to null and reports zero actual orders/fills.

## CSV schema

Comma-delimited, UTF-8 with header:

    venue,symbol,origin,closed,opened_at,closed_at,bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close

- Venue: exact market/broker venue and environment, e.g. a *verified*
  platform/account feed identifier, not a generic spot/futures mix.
- Symbol: platform-native instrument name.
- Origin: honest data provenance, never a claim of independent verification.
- Closed: must explicitly be true or 1, never a live candle.
- Opened_at / closed_at: ISO-8601 timestamps with UTC offset.
- Bid/Ask OHLC: independently observed values, not guessed using fixed spread.
- One market per file. Bars must be chronological and nonoverlapping. Weekend
  gaps are permitted.
- Do not commit licensed/third-party data or private user history.

Examples of OHLC use the *same timestamp interval* for Bid and Ask. Open/close
and independent high/low extrema are validated for crossed spreads.

## Scope of safeguards

The audit excludes the entire candle containing the Telegram publication
time (conservative approach), and never uses candles not fully closed
by the specified cutoff.

If entry and exit levels appear together, or both exit boundaries appear
in one candle, the result remains *ambiguous*. A gap across a boundary is
marked unpriced. Optional **open-spread percent** thresholds mark the
observation as *blocked* rather than counting an apparent win or loss.

The SQLite journal accepts spread vetoes as research-only events.

## Read-only MetaTrader 5 tick bridge (not connected to a user account)

The adapter method MT5Adapter.quote_history() can request a bounded window
of quote ticks using the MetaTrader5 COPY_TICKS_INFO interface. It takes
explicit start/end/as_of timestamps and a broker-specific venue label,
then passes the tick snapshots through aggregate_bidask_ticks().

- This interface has **not yet been exercised against an authenticated
  XM terminal**. Its automated tests use an in-memory fake MT5 object.
- Actual terminal access requires the broker application and the
  MetaTrader5 Python library on a compatible host. GitHub stores the code
  but does not provide a terminal or a continuously running robot.
- Broker-specific tick history may be truncated, sparse or unavailable.
  Coverage and timezone behavior must be checked before drawing conclusions.
- Each output bar's open/close represent the first and last **observed tick**
  in the UTC-aligned interval; missing intervals are not interpolated.
- Ticks arriving after the specified cutoff, invalid quotes, crossed spreads,
  unsorted timestamps and incomplete final bars are rejected or omitted.
- The connector uses ONLY COPY_TICKS_INFO, never order_send; real order
  submission remains disabled in the entire prototype.

## What is still missing?

1. Reliable, authorized platform-native historical **bid and ask** feed for
   the intended venue, with provenance, timestamp and completeness checks.
2. Test that broker timestamps/market sessions and spreads are correct.
3. Quote-gap handling, missing-data quality grades and tick-level order modeling.
4. Clearly specify market/limit/stop-entry order semantics.
5. Backtests with realistic fees, funding, slippage, overnight rules,
   commissions and capital constraints.
6. Sandbox order reconciling only after the read-only phase is validated.

**This tool has not measured strategy performance. Do not present target touches as realized profit.**
