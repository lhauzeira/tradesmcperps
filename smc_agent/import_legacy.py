"""Private local preflight for the normalized Telegram signal-audit CSV.

This module contains no Telegram messages and does not contact Telegram or
any market feed. It reports *data quality*, never a historic win rate.
Never commit the user's original export or parsed rows to a public repository.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import json
from math import isfinite
from pathlib import Path


REQUIRED_COLUMNS = {
    "id", "date", "category", "side", "symbol", "entry_type",
    "entry", "stop", "target", "rr_label", "rr_calc",
    "duplicate_of_prior", "time_diff_hours", "candle_used_future_minutes",
}


def flags_for_row(row: dict[str, str]) -> set[str]:
    """Flags are observations, not proof of causality or trading results."""
    flags = set()
    entry_type = row.get("entry_type", "")
    if entry_type == "zone_only":
        flags.add("SETUP_WITHOUT_FIXED_ENTRY")
    elif entry_type == "retracement_zone":
        flags.add("RETRACEMENT_REQUIRES_FILL_RULE")
    elif entry_type != "quoted_entry":
        flags.add("UNKNOWN_ENTRY_TYPE")

    if row.get("duplicate_of_prior", "").strip().lower() in ("true", "1", "yes"):
        flags.add("REPEATED_PARAMETERS")

    def optional_float(key):
        text = row.get(key, "").strip()
        if not text:
            return None
        try:
            result = float(text)
        except ValueError:
            flags.add("MALFORMED_NUMBER")
            return None
        if not isfinite(result):
            flags.add("MALFORMED_NUMBER")
            return None
        return result

    future = optional_float("candle_used_future_minutes")
    if future is not None and future > 1:
        flags.add("CANDLE_TIMESTAMP_REVIEW")
    printed_diff = optional_float("time_diff_hours")
    if printed_diff is not None and abs(printed_diff) > 1:
        flags.add("SCHEDULE_OR_TIMEZONE_REVIEW")

    try:
        timestamp = datetime.strptime(row.get("date", ""), "%d.%m.%Y %H:%M:%S GMT%z")
        if timestamp.utcoffset() is None:
            flags.add("INVALID_MESSAGE_TIMESTAMP")
    except ValueError:
        flags.add("INVALID_MESSAGE_TIMESTAMP")

    if entry_type != "zone_only":
        entry, stop, target = [optional_float(field) for field in ("entry", "stop", "target")]
        if entry is None or stop is None or target is None:
            flags.add("MISSING_PRICE_LEVEL")
        elif not all(value > 0 for value in (entry, stop, target)):
            flags.add("INVALID_PRICE_ORDER")
        else:
            direction = row.get("side", "").upper()
            if (direction == "BUY" and not (stop < entry < target)) or (
                direction == "SELL" and not (target < entry < stop)
            ) or direction not in ("BUY", "SELL"):
                flags.add("INVALID_PRICE_ORDER")
            risk = abs(entry - stop)
            rr = abs(entry-target) / risk if risk > 0 else None
            label = optional_float("rr_label")
            if label is not None and rr is not None and abs(rr-label) > 0.06:
                flags.add("RR_LABEL_MISMATCH")

    # The CSV deliberately does not establish which execution market supplied
    # the quotes; identical names can mean different contracts or venues.
    flags.add("VENUE_FEED_MAPPING_REQUIRED")
    return flags


def summarize_csv(path: str | Path) -> dict:
    """Only aggregated non-personal results are returned."""
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
            raise ValueError("Unexpected CSV columns: expected normalized signal-audit export")
        total = complete = 0
        categories = Counter()
        issues = Counter()
        distinct_levels = set()
        for row in reader:
            total += 1
            category = row.get("category", "").strip()
            categories[category] += 1
            flags = flags_for_row(row)
            issues.update(flags)
            if all(row.get(key, "") for key in ("entry", "stop", "target")):
                complete += 1
                distinct_levels.add(tuple(row.get(key, "").strip() for key in (
                    "category", "symbol", "side", "entry", "stop", "target"
                )))
    return {
        "rows": total,
        "records_with_three_price_levels": complete,
        "distinct_quoted_parameter_combinations": len(distinct_levels),
        "categories": dict(sorted(categories.items())),
        "quality_flags": dict(sorted(issues.items())),
        "execution_or_trade_outcome_verified": False,
        "historical_win_rate": None,
        "notes": [
            "Repeated price combinations are not automatically multiple executed orders.",
            "Printed-time differences may reflect scheduling or timezones, not lookahead.",
            "No executions or market candles were imported; no P&L can be inferred.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Private aggregate audit of exported signals")
    parser.add_argument("--csv", required=True, help="Path to private normalized audit CSV")
    args = parser.parse_args()
    print(json.dumps(summarize_csv(args.csv), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
