# XM GOLD demo snapshot — conservative risk calculations (v0.5 DRAFT)

This document and the risk calculator are based on screenshot(s) of the
MetaTrader 5 GOLD instrument specification, as shown by the user.
**They are not a live authenticated broker contract, order authorization,
or investment recommendation.** Instrument specifications may change.

## Snapshot observed

| Setting | Observed on MT5 |
|---|---|
| Broker server | XMGlobal-MT5 5, demo |
| Symbol | GOLD (CFD) |
| Contract size | 100 |
| Quote digits | 2 |
| Tick size | 0.01 |
| Tick value | USD 1 per tick per 1 lot, as shown in specification |
| Minimum volume | 0.01 lot |
| Maximum volume | 50 lots |
| Volume step | 0.001 lot |
| Swap calculation | In points |
| Long swap | -69.5 points (snapshot) |
| Short swap | +15.07 points (snapshot) |
| Wednesday swap coefficient | 3x |
| Price shown on chart | Bid |
| Execution type | Market |

**Displayed Monday session only:** quotations 01:00–23:59 and trading
01:02–23:58 on the platform/server clock. The screenshots do **not**
establish Tuesday–Sunday hours, the historical June GMT offset, or the
exact applicability of the current swap figures to past positions.

The minimum lot is **0.01**, whereas the step is **0.001**. Therefore
0.011 is a mathematically valid volume given these two settings, while
0.009 is below minimum and 0.0105 violates the step. The live server
must still validate all proposed volume orders in any future execution
implementation.

## Risk calculations: zero orders, no account access

Run:

    python -m smc_agent.xm_gold_risk

To compute a budgeted research-only lot size programmatically:

    from smc_agent.xm_gold_risk import size_under_risk_budget
    estimate = size_under_risk_budget(
        side="buy",
        entry="4000.00",
        stop="3999.00",
        risk_budget_usd="5.00",
        extra_cost_reserve_usd="1.00",
    )
    print(estimate)

This example uses **fabricated** entry and stop values and an
arbitrary illustrative budget, **not** the user's financial resources
and **not** any live market price.

At the contract snapshot's USD 1 tick value and USD 0.01 tick size,
the **theoretical stop-distance** risk of a USD 1 GOLD move equals:

    1.00 lot -> USD 100
    0.10 lot -> USD 10
    0.01 lot -> USD 1

This does **not** include potential spread, commissions, swap, margin,
currency differences, funding, market gaps, partial fills, slippage
beyond stop, or trading sessions. A caller **must supply** a separate
cost/slippage reserve. Even then, actual losses may exceed the reserve.
A trading account's available margin and broker stop/freeze rules are
outside this calculator.

Fail closed: if the minimum volume does not fit the budget after
the explicitly stated reserve, return NO_TRADE, never increase the
client's risk budget. If a proposed price is not aligned to the USD 0.01
tick, or a lot is below minimum or off step, reject it.

## Important: swap units are points, not realized USD

The screenshot showed swap long -69.5, swap short +15.07 and
Wednesday coefficient 3, with method *in points*. These are recorded
for reference, not automatically charged or credited in risk sizing.
Rollover time, contract valuation, calendar, holidays and any changing
swap rates must be confirmed separately from the live MT5 broker
before modeling overnight positions.

## Future tasks

- Obtain instrument specifications via the **read-only** MT5 API and
  compare them with the screenshot, avoiding false assumptions.
- Verify actual historical server UTC offset and weekday sessions.
- Obtain the complete Bid/Ask data set, with gaps and quote-update
  coverage accounted for, before evaluating any past alert.
- Define order types, actual stop-fill behavior, commission, margin,
  overnight financing and platform-specific policies.
- Reconcile forward paper trading and actual broker fills separately.
- Keep send_order blocked; no live trading, no verified profits yet.
