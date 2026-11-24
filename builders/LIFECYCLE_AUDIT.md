# Signal lifecycle — v0.3 experimental audit

## Purpose

Distinguish *a signal posted in Telegram* from *a market price touching its proposed
entry* and from *an actual broker order being filled and settled*.

The code here implements only the second category: **OHLC price-level observation**.
It cannot verify fills, commissions, slippage, stop order execution, or P&L.

## State flow

    posted -> waiting for future candles -> entry level touched
       -> stop price level touched (price-only)
       -> target price level touched (price-only)
       -> ambiguous (if event sequencing cannot be proved)
       -> horizon expired or unresolved

No state above implies that an order was placed.

## Anti-lookahead policy

1. Use the Telegram **publication time**, not an unexplained internal "signal time".
2. Use the native exchange/broker feed for the exact symbol and venue.
3. Exclude any bar opened at or before the publication, including the containing bar.
4. Exclude bars not fully closed by the observation cutoff.
5. A candle containing both an entry and a stop/target is *ambiguous*: OHLC does not
   establish which price was crossed first.
6. An exit candle touching both boundaries is also ambiguous.
7. A gap opening beyond a boundary is marked *unpriced*, not as a realized +R/-R.
8. An entry-level touch does not prove a fill.
9. Expire signals after a configured number of observation bars and keep unresolved
   states visible. Never silently discard losses or expired opportunities.
10. Never transfer a trade's OHLC outcome across MT5 spot CFD, CME futures or
    MyFundedPerps perpetuals using an unverified fixed price offset.

## Run synthetic tests (no internet or credentials)

    python -m unittest discover -s tests -v

## Privately audit the normalized Telegram export

The audit CSV previously prepared by the researcher contains categories, price
parameters, date fields and flags; it **must not** be committed.

Run this locally where the CSV exists:

    python -m smc_agent.import_legacy --csv "/path/to/ICC_Bot_Auditoria_2026.csv"

The command prints only aggregate counts and issues, not the conversations or names.
It explicitly returns historical_win_rate = null.

It flags repeated price parameters, potential timestamp differences, retroactive
candle labels and inconsistent level order or risk/reward calculations. A timestamp
flag calls for clarification and does not itself prove fraud or lookahead bias.

## Development work not yet complete

- Connect and verify historical **closed bid/ask quotes** with platform-native
  prices (not just OHLC midpoint bars).
- Define order type: market, stop, limit, TTL, spread, entry tolerance and fees.
- Model partial fills, actual order IDs, broker confirmations, stops and rejects.
- Reconcile the ICC and SMC signal generators against their published timestamps.
- Use out-of-sample and forward data; report ambiguous observations separately.
- Only then calculate robust expectancy and net results.
- Keep all real order transmission disabled during this experimental phase.

## Data policy

Do **not** commit Telegram HTML, the private normalized CSV, .rdp files,
API keys, contact lists, channel usernames, account numbers or personal messages
to the public GitHub repository.

This module is provided for auditing research, not trade recommendations.
