# SMC Trading Agent — Builders Prototype

**Status:** experimental, deterministic trading-research prototype. **No real or simulated brokerage orders are sent.** No returns or pass rates are claimed.

A proof-of-concept that transforms selected Smart Money Concepts (SMC) rules into reproducible Python analysis:
- macro structure using confirmed fractal highs/lows;
- candle-close break of structure (BOS);
- full-wick order block (OB) with 50% mitigation;
- candle-close confirmation for entry proposals;
- conservative per-trade risk gate;
- separate read-only adapters for MT5 (XM) and MyFundedPerps sandbox.

This is a compact implementation. Additional experiments with ATR-confirmed ZigZag, liquidity and volume confluences are maintained separately and still need to be reconciled.

## Demonstration

Requires Python 3.11+ and no third-party packages:

    python -m unittest discover -s tests -v
    python -m smc_agent.demo

The CLI demo reports deterministic metrics about **synthetic candles**, and expressly confirms that zero orders were sent and that no real market data was used.

The same commands run in [GitHub Actions](https://github.com/lhauzeira/tradesmcperps/actions). See [detailed demo instructions](builders/DEMO.md).

## Integrations

**MetaTrader 5 (XM):** The adapter provides a local terminal-based historical candle reader. Requires Windows, an MT5 terminal, and a separately installed MetaTrader5 Python package. It has not been tested against a personal account.

**MyFundedPerps:** The sandbox adapter is read-only, requires an API key beginning in fp_test_, and intentionally rejects live keys. The API is in beta; verify endpoint stability and your actual access before connecting. **Never commit API keys, passwords or personal credentials.**

**Execution methods deliberately raise exceptions.** Safety, broker contract specifications, bid/ask, costs, historical forward tests and prop-firm limits have not been validated.

## Roadmap

1. Confirm automated tests and reproduce the demo.
2. Integrate additional algorithmic features from the richer local prototype.
3. Validate time-aligned native feeds and account policies in read-only mode.
4. Perform realistic backtesting and out-of-sample analysis.
5. Design and test an idempotent sandbox execution adapter with protected exits.
6. Review risk compliance before any trading or account purchase.

Project status: [PROJECT_STATUS.md](PROJECT_STATUS.md).

*Research software only. This is not investment advice.*
