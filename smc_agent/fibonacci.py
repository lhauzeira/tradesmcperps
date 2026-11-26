"""Research Fibonacci retracements anchored in CLOSED/CONFIRMED SMC pivots.

No look-ahead: a swing endpoint is eligible only after the fractal wing
has fully closed. Fibonacci levels are price geometry, not evidence of
support/resistance, fillability, expected returns or profitability.

Values are generic relative price levels. They do NOT assume GOLD ticks,
forex pips, contract sizes, trading sessions or lot economics.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .engine import Candle, Pivot, atr_at, confirmed_pivots, _chronological


RATIOS = (0.5, 0.618, 0.705, 0.786)


@dataclass(frozen=True)
class FibonacciObservation:
    side: str
    from_index: int
    to_index: int
    confirmed_at: int
    start_price: float
    end_price: float
    price_50: float
    price_618: float
    price_705: float
    price_786: float
    zone_low: float
    zone_high: float
    latest_close: float
    status: str

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError("Fibonacci direction invalid")
        if not 0 <= self.from_index < self.to_index <= self.confirmed_at:
            raise ValueError("Future or reversed Fibonacci swing")
        if any(not isfinite(v) or v <= 0 for v in (
            self.start_price, self.end_price, self.price_50,
            self.price_618, self.price_705, self.price_786,
            self.zone_low, self.zone_high, self.latest_close
        )):
            raise ValueError("Invalid positive price")
        if self.zone_low > self.zone_high:
            raise ValueError("Invalid OTE zone")

    @property
    def in_ote_zone(self) -> bool:
        return self.status == "EM_ZONA_OTE"

    @property
    def recent_ote_retest(self) -> bool:
        return self.status in ("EM_ZONA_OTE", "RETESTE_RECENTE_OTE")

    def ob_overlaps_ote(self, ob_low: float, ob_high: float) -> bool:
        if not isfinite(ob_low) or not isfinite(ob_high) or ob_low <= 0 or ob_low > ob_high:
            raise ValueError("Invalid Order Block range")
        if self.status == "SWING_INVALIDADO":
            return False
        return ob_low <= self.zone_high and ob_high >= self.zone_low


def _levels(side: str, start_price: float, end_price: float) -> tuple[float, ...]:
    if side == "buy":
        if not start_price < end_price:
            raise ValueError("Buy impulse must be low to high")
        return tuple(end_price - ratio * (end_price - start_price) for ratio in RATIOS)
    if side == "sell":
        if not start_price > end_price:
            raise ValueError("Sell impulse must be high to low")
        return tuple(end_price + ratio * (start_price - end_price) for ratio in RATIOS)
    raise ValueError("Direction must be buy or sell")


def observe_fibonacci(
    candles: list[Candle], *, side: str, wing: int = 2,
    max_lookback: int = 120, max_impulse_bars: int = 80,
    min_impulse_atr: float = 1.5, retest_recent_bars: int = 6,
) -> FibonacciObservation | None:
    """Find the last confirmed directional low->high/high->low impulse.

    The anchor low/high MUST precede the terminal confirmed pivot. We
    never use a still-unconfirmed extreme to redraw historical setups.
    If no credible, recent swing exists, report None rather than guess.

    Level 0.618--0.786 is an illustrative OTE research band; checking
    overlapping prices alone does not mean a tradable fill occurred.
    """
    _chronological(candles)
    if side not in ("buy", "sell"):
        raise ValueError("Invalid side")
    if wing < 1 or max_lookback < 20 or max_impulse_bars < wing * 2 + 1:
        raise ValueError("Invalid pivot window")
    if not isfinite(min_impulse_atr) or min_impulse_atr <= 0:
        raise ValueError("Invalid minimum impulse multiple")
    if retest_recent_bars < 1:
        raise ValueError("Invalid OTE retest window")
    if len(candles) < 20:
        return None

    available = len(candles) - 1
    all_pivots = confirmed_pivots(candles, wing=wing, available_at=available)
    first_allowed = max(0, len(candles) - max_lookback)
    pivots = [p for p in all_pivots
              if p.index >= first_allowed and p.confirmed_at <= available]
    direction_end = "high" if side == "buy" else "low"
    direction_start = "low" if side == "buy" else "high"

    for end in reversed(pivots):
        if end.kind != direction_end:
            continue
        # A detected impulse cannot be assessed before its end is confirmed.
        a = atr_at(candles, end.confirmed_at)
        if a is None or a <= 0:
            continue
        possible = [
            p for p in pivots
            if p.kind == direction_start and p.index < end.index
            and p.confirmed_at < end.index
            and end.index - p.index <= max_impulse_bars
        ]
        for start in reversed(possible):
            if side == "buy" and start.price >= end.price:
                continue
            if side == "sell" and start.price <= end.price:
                continue
            if abs(end.price - start.price) < a * min_impulse_atr:
                continue

            level_50, level_618, level_705, level_786 = _levels(
                side, start.price, end.price
            )
            zone_low = min(level_618, level_786)
            zone_high = max(level_618, level_786)
            recent_from = max(end.index + 1, len(candles) - retest_recent_bars)
            rest = candles[end.index + 1:]

            # A confirmed swing is no longer a valid directional context
            # if a later CLOSED candle breaches its anchor.
            invalidated = (
                any(x.close < start.price for x in rest) if side == "buy"
                else any(x.close > start.price for x in rest)
            )
            current = candles[-1].close
            if invalidated:
                status = "SWING_INVALIDADO"
            elif zone_low <= current <= zone_high:
                status = "EM_ZONA_OTE"
            elif any(x.low <= zone_high and x.high >= zone_low
                     for x in candles[recent_from:]):
                status = "RETESTE_RECENTE_OTE"
            else:
                status = "AGUARDANDO_RETRACAO_OTE"

            return FibonacciObservation(
                side=side, from_index=start.index, to_index=end.index,
                confirmed_at=end.confirmed_at, start_price=start.price,
                end_price=end.price, price_50=level_50,
                price_618=level_618, price_705=level_705, price_786=level_786,
                zone_low=zone_low, zone_high=zone_high,
                latest_close=current, status=status
            )

    return None
