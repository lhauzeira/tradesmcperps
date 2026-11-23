# SMC Trading Agent — project status (v0.1)

## Goal
Build a deterministic Smart Money Concepts (SMC) strategy engine reusable by two read-only adapters: MetaTrader 5 (XM CFD) and MyFundedPerps sandbox (perpetual contracts). This repository is for research and the MyFundedPerps Builders Program prototype application.

## Available locally (package prepared outside GitHub)
- Python strategy module with causal confirmed fractals, ATR-based ZigZag, structural break, full-wick order blocks, 50% mitigation, close-confirmed entry and liquidity/volume confluences.
- MT5 adapter for reading historical closed bars, account and positions.
- MyFundedPerps sandbox API read-only adapter.
- Risk check for minimum MT5 lot.
- 10 passing offline unit tests on the prepared local package.
- Synthetic demonstration with no profit claim.

**Important:** Those Python files are not yet tracked in this GitHub repository. The complete local package must be copied into the repository and reviewed separately. Do not describe this repository as a fully published executable prototype yet.

## Safety
- No real orders; both send_order methods are intentionally disabled.
- Never commit API keys, account details, trading tokens, or `.env` files.
- Broker feeds and contract specifications must be validated separately; XM CFD prices must not be used as the sole execution feed for MyFundedPerps.
- Profitability, execution safeguards, and proprietary-firm rule compliance have not been validated.

## Next deliverables
1. Import full reviewed Python package, tests, and synthetic example data.
2. Run tests in a clean checkout, establish CI and public demo instructions.
3. Test each connection with its own data feed in read-only mode.
4. Implement backtest with spread, fees, slippage, walk-forward evaluation.
5. Only after validated sandbox execution safeguards, consider controlled order execution.
