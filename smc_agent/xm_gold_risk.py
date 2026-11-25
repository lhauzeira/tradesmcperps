"""XM demo GOLD: transparent risk-math prototype from MT5 instrument screenshots.

SOURCE: user's MT5 GOLD symbol specification screenshots (snapshot only).
No live broker query, no order sending, no access to account balances.
All position sizes are calculations, NOT permission to trade.

IMPORTANT:
- Stop price execution can slip; this module only budgets a *user-provided*
  dollar reserve on top of the theoretical stop loss.
- Broker margin, commissions, market hours, swap, existing exposure and
  margin/equity account rules are NOT verified by this module.
- Tick value can vary by account/symbol/currency and over time; re-check
  live symbol_info before future integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any


def D(value: Any, name: str) -> Decimal:
    """Return finite decimal without binary float rounding in calculations."""
    if isinstance(value, bool):
        raise ValueError(f"{name} cannot be boolean")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid {name}") from None
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class GoldContractSnapshot:
    """Screen-observed broker settings; not an authenticated live quote."""
    venue: str = "XMGlobal-MT5 5 (demo)"
    symbol: str = "GOLD"
    tick_size: Decimal = Decimal("0.01")
    tick_value_usd_per_lot: Decimal = Decimal("1")
    contract_size: Decimal = Decimal("100")
    lot_min: Decimal = Decimal("0.01")
    lot_max: Decimal = Decimal("50")
    lot_step: Decimal = Decimal("0.001")
    # Swap fields are in points, not USD, and never included automatically
    swap_long_points: Decimal = Decimal("-69.5")
    swap_short_points: Decimal = Decimal("15.07")
    wednesday_swap_multiplier: int = 3

    def __post_init__(self):
        if not self.venue or not self.symbol:
            raise ValueError("Broker and instrument required")
        for key in ("tick_size", "tick_value_usd_per_lot", "contract_size",
                    "lot_min", "lot_max", "lot_step"):
            val = D(getattr(self, key), key)
            if val <= 0:
                raise ValueError(f"{key} must be positive")
        if D(self.lot_min, "lot_min") > D(self.lot_max, "lot_max"):
            raise ValueError("Minimum volume exceeds maximum")
        for key in ("swap_long_points", "swap_short_points"):
            D(getattr(self, key), key)
        if self.wednesday_swap_multiplier != 3:
            raise ValueError("Screenshot documents a Wednesday triple swap")

    def valid_volume(self, volume: Any) -> Decimal:
        value = D(volume, "volume")
        if not (self.lot_min <= value <= self.lot_max):
            raise ValueError("Volume outside broker lot range")
        if (value / self.lot_step) != (value / self.lot_step).to_integral_value():
            raise ValueError("Volume must be multiple of broker step")
        return value


XM_GOLD_DEMO_SNAPSHOT = GoldContractSnapshot()


@dataclass(frozen=True)
class PositionEstimate:
    status: str
    volume_lots: Decimal | None
    theoretical_stop_loss_usd: Decimal | None
    extra_cost_reserve_usd: Decimal
    total_budgeted_loss_usd: Decimal | None
    risk_budget_usd: Decimal
    reason: str


def _validated_levels(entry: Any, stop: Any, side: str, spec: GoldContractSnapshot):
    entry, stop = D(entry, "entry"), D(stop, "stop")
    if entry <= 0 or stop <= 0:
        raise ValueError("Prices must be positive")
    if side not in ("buy", "sell"):
        raise ValueError("Side must be 'buy' or 'sell'")
    if side == "buy" and stop >= entry:
        raise ValueError("Long stop must be lower than entry")
    if side == "sell" and stop <= entry:
        raise ValueError("Short stop must be higher than entry")
    for value in (entry, stop):
        ticks = value / spec.tick_size
        if ticks != ticks.to_integral_value():
            raise ValueError("Prices must follow instrument tick size")
    return entry, stop


def theoretical_stop_loss_usd(
    *, side: str, entry: Any, stop: Any, volume_lots: Any,
    spec: GoldContractSnapshot = XM_GOLD_DEMO_SNAPSHOT,
) -> Decimal:
    """Math for quote-defined stop distance, NOT an actual worst-case fill."""
    entry, stop = _validated_levels(entry, stop, side, spec)
    lots = spec.valid_volume(volume_lots)
    return (abs(entry - stop) / spec.tick_size
            * spec.tick_value_usd_per_lot * lots)


def size_under_risk_budget(
    *, side: str, entry: Any, stop: Any, risk_budget_usd: Any,
    extra_cost_reserve_usd: Any,
    spec: GoldContractSnapshot = XM_GOLD_DEMO_SNAPSHOT,
) -> PositionEstimate:
    """Choose greatest valid broker-step volume without exceeding the cap.

    If even the *minimum* lot won't fit the given risk budget, return NO_TRADE.
    The caller must explicitly supply a reserve for costs/slippage; this is
    not a guarantee the reserve is enough, nor a test of broker margin.
    """
    entry, stop = _validated_levels(entry, stop, side, spec)
    budget = D(risk_budget_usd, "risk_budget_usd")
    reserve = D(extra_cost_reserve_usd, "extra_cost_reserve_usd")
    if budget <= 0 or reserve < 0:
        raise ValueError("Risk budget must be positive; reserve nonnegative")
    loss_per_lot = abs(entry-stop) / spec.tick_size * spec.tick_value_usd_per_lot
    if budget <= reserve:
        return PositionEstimate(
            "NO_TRADE", None, None, reserve, None, budget,
            "Budget does not cover explicitly reserved costs")

    available = budget-reserve
    unconstrained_lots = available / loss_per_lot
    maximum_candidate = min(spec.lot_max, unconstrained_lots)
    steps = (maximum_candidate / spec.lot_step).to_integral_value(rounding=ROUND_FLOOR)
    lots = steps * spec.lot_step
    if lots < spec.lot_min:
        return PositionEstimate(
            "NO_TRADE", None, None, reserve, None, budget,
            "Minimum broker volume would breach budget")
    lots = spec.valid_volume(lots)
    stop_loss = loss_per_lot * lots
    total = stop_loss + reserve
    if total > budget:
        raise AssertionError("Risk budget implementation violated")
    return PositionEstimate(
        "RESEARCH_SIZE_ONLY", lots, stop_loss, reserve, total, budget,
        "No margin check, no fee schedule, no broker execution or authorization")


def risk_example() -> dict[str, str | bool]:
    """Illustrate known contract math; no personal capital or position advice."""
    snapshot = XM_GOLD_DEMO_SNAPSHOT
    result = size_under_risk_budget(
        side="buy", entry="4000.00", stop="3999.00",
        risk_budget_usd="5.00", extra_cost_reserve_usd="1.00",
        spec=snapshot,
    )
    return {
        "dataset": "SYNTHETIC_PRICE_LEVELS_AND_USER_SCREENSHOT_CONTRACT",
        "symbol": snapshot.symbol,
        "venue": snapshot.venue,
        "lot_min": str(snapshot.lot_min),
        "lot_step": str(snapshot.lot_step),
        "theoretical_loss_for_0_01_lot_usd": str(theoretical_stop_loss_usd(
            side="buy", entry="4000", stop="3999", volume_lots="0.01")),
        "example_research_lots": str(result.volume_lots),
        "example_risk_cap_usd": str(result.risk_budget_usd),
        "example_reserved_extra_cost_usd": str(result.extra_cost_reserve_usd),
        "example_total_budgeted_usd": str(result.total_budgeted_loss_usd),
        "status": result.status,
        "orders_sent": "0",
        "actual_broker_fill_verified": False,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(risk_example(), indent=2, ensure_ascii=False))
