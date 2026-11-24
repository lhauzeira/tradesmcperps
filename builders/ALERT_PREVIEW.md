# Signal preview / Telegram research track (v0.2 draft)

This module is **not a Telegram bot yet**. It never uses the Telegram API or sends anything.

The purpose is to isolate signal **generation and documentation** from delivery, so the strategy can be tested without distributing invented or unvalidated entries to traders.

## Reproduce

Requires Python 3.11+, no account, keys or packages.

    python -m smc_agent.alert_demo
    python -m unittest discover -s tests -v

Output is explicitly labelled synthetic: \`TEST_SYNTH\` with fabricated prices, not a real market alert. It includes close time, entry, stop, target, ratio, reason and unique event ID.

## Safeguards

- Timezone-aware UTC timestamp of closed bar.
- Price side validation and consistency between target/stop and RR.
- HTML escaping of the explanation before a potential Telegram HTML message.
- Stable alert ID to suppress duplicated signals **during a single process session only**.
- Zero orders and zero network requests.

## Not implemented

- Direct exchange/broker market feeds and verification of market-close timestamps.
- Durable deduplication after process restarts.
- Signal quality score, risk-cost-adjusted expectancy, historical outcome tracking.
- Telegram Bot API connection; there are **no message dispatch or Telegram API keys**.
- Proven success or profitability metrics.

No external third-party bot source code has been reviewed or used to create this module.

## Intended next step

Add a real-time read-only data ingestion adapter and a persisted signal journal; then run out-of-sample forward observation before enabling Telegram notifications to an explicitly authorized destination.
