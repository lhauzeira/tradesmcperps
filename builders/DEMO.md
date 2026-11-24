# SMC Trading Agent — Builders Program demo

## What it is
An open-source, deterministic research prototype for Smart Money Concepts (SMC) with confirmed pivots, BOS, full-wick order blocks, 50% mitigation checks and an explicit risk gate.

## What it does not do
It does not submit orders, connect live trading accounts, calculate verified trading performance, or claim a profitable trading strategy. The included demo uses synthetic candles only.

## Requirements
Python 3.11 or newer. No pip packages are needed for the offline demo.

## Run the demo
From the repository root:

    python -m smc_agent.demo

## Run automated tests
From the repository root:

    python -m unittest discover -s tests -v

## Development roadmap
1. Compare this implementation with the richer offline ZIP prototype and reconcile differences.
2. Complete platform-native read-only adapters for MetaTrader 5 (XM) and MyFundedPerps.
3. Capture and normalize platform-native closed candles.
4. Add historical simulation with costs, spreads, funding, drawdown and out-of-sample validation.
5. Validate exchange/broker specifications and prop-firm rules.
6. Only then consider guarded sandbox execution and idempotent order protection.

Repository: https://github.com/lhauzeira/tradesmcperps
