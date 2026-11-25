# GOLD paper replay — version 0.6 (DRAFT, 100% offline)

**Research-only model. No user account is accessed, no order is sent, no
historical or realized profitability is established.** In this module,
"PAPER_TARGET_MODEL" and "PAPER_STOP_MODEL" mean hypothetical
price-boundary events under an explicit simulation policy.

## Why trading sessions matter

Your broker can publish prices before or after it accepts orders. The MT5
GOLD instrument screenshot showed **Monday only**:
quotations 01:00–23:59 and trading 01:02–23:58 in the terminal clock.
We do not know the remaining weekdays from that screenshot, and we have
not independently verified whether exported historical ticks use the
same server clock.

For this reason, v0.6 deliberately does NOT invent a Tuesday–Friday
calendar, does NOT guess the XM historical server UTC offset and does
NOT allow an unknown session to produce a modeled winning trade.
Missing weekday information or missing verified offset => SESSION_UNVERIFIED.
The Monday screenshot is retained in builders/XM_GOLD_RISK.md only;
it is **not** used as permission to trade real money.

## What was implemented

Source: smc_agent/paper.py.

- Model a **market-next-bar-open** order only; limit and stop-entry
  orders require separate modeling and are not inferred from ICC alerts.
- Use an exact bid/ask quote feed for the chosen market.
- Require the candidate entry bar to begin after the signal publication,
  be completely closed at the observation cutoff, arrive within an
  explicit maximum latency, and be in a verified trading session.
- Use ASK open to model long entry and BID open to model short entry.
  Buy stop/target observation uses BID high/low; sell stop/target uses
  ASK high/low.
- Require explicit cost assumptions: budget in USD, reserve for other
  costs, hypothetical commission per lot, slippage each side, maximum
  entry price drift, maximum spread, expected quote-bar length and
  maximum observation bars. These are **not** claimed to be XM fees.
- Size lots under the theoretical stop budget using the observed
  contract snapshot and volume step. If the minimum lot cannot fit,
  return NO_TRADE_MIN_LOT_RISK.
- Count paper model profit/loss only in unambiguous level-touch cases
  with uninterrupted, verified sessions. Gross/net values are
  hypothetical, **never** realized P&L.
- Mark ambiguous OHLC bar sequencing, gaps, missing/closed sessions,
  stale quotes, price drift and excessive spread without a made-up
  winning outcome.
- NEVER call MT5 order_send, Telegram, the network or a trading API.

Price-level triggers do not prove a real fill. Further work is required
to reconcile true ticks, market/limit order book mechanics, slippage
distributions, historical sessions, fees and financing costs.

## Demo: fabricated quotes and fabricated calendar

Run from project root:

    python -m smc_agent.paper_demo
    python -m unittest discover -s tests -v

The demo is explicitly **SYNTHETIC_ONLY**, with a fake Monday UTC session
and a deliberately fabricated price series. It demonstrates a
PAPER_TARGET_MODEL result but **zero verified fills** and zero sent orders.

The same exact synthetic data with unverified session offset is blocked
with SESSION_UNVERIFIED; the experiment never silently authorizes trading.

## Audit all scenarios, not just winners

Source: smc_agent/paper_report.py

The batch reporter summarizes **every** submitted paper event and refuses
duplicate signal IDs. It keeps separate counts for modeled target touches,
modeled stop touches, and all blocked/inconclusive scenarios.

It can show the arithmetic sum of modeled outcomes **for the resolved
subset only**, but deliberately leaves verified win rate, verified profit
factor and realized broker P&L unset. A report limited to resolved
simulations would otherwise produce misleading headline statistics.

Do not convert these partial-paper metrics into client performance,
trading recommendations, or Builders Program adoption/profitability
claims. Count all attempted signals, report exclusions and subsequently
validate on out-of-sample native broker data.

## No historical ICC performance claims

The user's Telegram historical messages are not broker fills and may
have scheduled times unlike the original publication time. Also GOLD on
XM is not guaranteed to match XAUUSD on another venue.

Before evaluating actual historical outcomes, we will require:
- historical timezone and all market sessions confirmed for the broker;
- validated native GOLD Bid/Ask tick coverage, including update-only rows;
- an explicit order-entry policy and session/price gaps treatment;
- fees, spread, commission, slippage and overnight financing,
  or published bounds for plausible scenarios;
- clean separation of training, parameter fitting and out-of-sample tests;
- a separate report of ambiguous, expired, non-executed and missing-data
  events, so losing signals are not silently discarded.

The absence of the remaining MT5 screenshots does not prevent completing
the code or synthetic tests. It only limits claims about historical
trade feasibility.
