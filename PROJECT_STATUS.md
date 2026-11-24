# SMC Trading Agent — status

## Public repository status
The development branch now contains an **executable compact Python research prototype**:
- confirmed fractals (no use of future unclosed candles)
- simplified structural break (BOS) and full-wick order block detection
- check for 50% mitigation before candle-close confirmation
- conservative per-trade cash-risk gate (no martingale)
- read-only MetaTrader 5 and MyFundedPerps sandbox adapter classes
- deterministic offline demo and unit tests
- GitHub Actions configuration for automated offline tests

Run the demo:

    python -m smc_agent.demo

Run tests:

    python -m unittest discover -s tests -v

**Scope clarification:** the GitHub version is a **compact implementation**, not yet a byte-for-byte upload of the richer ZIP generated in ChatGPT. The ZIP contains extra ZigZag, volume/liquidity confluences, synthetic CSV fixtures and CLI features. It passed **10 offline tests locally**; GitHub CI results must be verified separately. The compact version currently has **7 tests**.

## Safety and limitations
- Zero order execution; both send_order methods always raise RuntimeError.
- Only sandbox MyFundedPerps tokens with prefix fp_test_ are accepted; no live tokens.
- API routes/host are experimental and require verification against current official beta documentation before connecting to any account.
- MyFundedPerps perpetual data and XM CFD data must be treated as distinct markets.
- No profitability, backtest, forward-test or challenge success demonstrated.
- The risk cap is an internal prototype rule, not a guarantee of prop firm compliance.
- Do not put API tokens, passwords or account details in GitHub or screenshots.

## Next milestones
1. Confirm GitHub CI executes and fix failures; then prepare an application demo.
2. Reconcile compact code with the complete local ZIP and port missing features.
3. Read platform-native candles and apply timestamp/contract-specific validation.
4. Backtest with transaction costs, drawdown and out-of-sample periods.
5. Validate sandbox and paper execution with guards, protected exits and idempotency.
6. Only after successful testing, discuss any execution automation.

No purchase or live trading is necessary to develop this research prototype.
