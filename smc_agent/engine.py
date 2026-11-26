"""Motor experimental SMC. Recebe apenas candles FECHADOS em UTC.

Não é uma estratégia validada nem envia ordens.
"""
from dataclasses import dataclass
from datetime import datetime
from statistics import mean


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = 0.0

    def __post_init__(self):
        if self.time.tzinfo is None or self.time.utcoffset() is None:
            raise ValueError("Timestamp deve incluir fuso horário")
        if self.low <= 0 or self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC inválido")


@dataclass(frozen=True)
class Pivot:
    index: int
    kind: str
    price: float
    confirmed_at: int


@dataclass(frozen=True)
class OrderBlock:
    side: str
    low: float
    high: float
    candle_index: int
    bos_index: int

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2


@dataclass(frozen=True)
class Signal:
    side: str
    entry: float
    stop: float
    target: float
    rr: float
    ob: OrderBlock
    reason: str


def _chronological(candles):
    if any(a.time >= b.time for a, b in zip(candles, candles[1:])):
        raise ValueError("Candles fora de ordem ou duplicados")


def atr_at(candles: list[Candle], index: int, period: int = 14) -> float | None:
    if period < 1 or index < period:
        return None
    tr = []
    for i in range(index - period + 1, index + 1):
        c, previous = candles[i], candles[i - 1]
        tr.append(max(c.high - c.low, abs(c.high - previous.close), abs(c.low - previous.close)))
    return mean(tr)


def confirmed_pivots(candles: list[Candle], wing: int = 2, available_at: int | None = None):
    """O pivô só existe após wing candles posteriores terem FECHADO."""
    if wing < 1:
        raise ValueError("wing inválido")
    end = len(candles) - 1 if available_at is None else min(available_at, len(candles) - 1)
    out = []
    for i in range(wing, end - wing + 1):
        others = [j for j in range(i - wing, i + wing + 1) if j != i]
        if all(candles[i].high > candles[j].high for j in others):
            out.append(Pivot(i, "high", candles[i].high, i + wing))
        if all(candles[i].low < candles[j].low for j in others):
            out.append(Pivot(i, "low", candles[i].low, i + wing))
    return out


def macro_bias(candles: list[Candle]) -> int:
    _chronological(candles)
    pivots = confirmed_pivots(candles)
    highs = [p.price for p in pivots if p.kind == "high"]
    lows = [p.price for p in pivots if p.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return 0
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return 1
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return -1
    return 0


def order_blocks(candles: list[Candle], wing: int = 2, min_body_atr: float = .85):
    """BOS = fechamento além de pivô confirmado; OB = última vela oposta inteira."""
    _chronological(candles)
    result = []
    for i in range(20, len(candles)):
        a = atr_at(candles, i - 1)
        if not a or abs(candles[i].close - candles[i].open) < min_body_atr * a:
            continue
        pivots = confirmed_pivots(candles, wing, available_at=i-1)
        for side, kind in (("buy", "high"), ("sell", "low")):
            eligible = [p for p in pivots if p.kind == kind and p.index >= i - 35]
            if not eligible:
                continue
            level = eligible[-1].price
            curr, prev = candles[i], candles[i - 1]
            broke = (curr.close > level >= prev.close and curr.close > curr.open) if side == "buy" else (
                curr.close < level <= prev.close and curr.close < curr.open)
            if not broke:
                continue
            for j in range(i-1, max(-1, i-9), -1):
                opposite = candles[j].close < candles[j].open if side == "buy" else candles[j].close > candles[j].open
                if opposite:
                    result.append(OrderBlock(side, candles[j].low, candles[j].high, j, i))
                    break
    return result


def analyze(macro: list[Candle], entry: list[Candle], rr: float = 2.5, *,
            require_fibonacci: bool = False) -> Signal | None:
    """Experimental SMC with OPTIONAL, not yet performance-tested Fibonacci.

    require_fibonacci=False preserves the previous GOLD SMC behavior.
    The filter, when requested, requires a confirmed directional swing,
    a recent OTE retest and overlap with the detected Order Block.
    """
    _chronological(macro)
    _chronological(entry)
    if not 2 <= rr <= 3 or len(macro) < 40 or len(entry) < 50:
        return None
    bias = macro_bias(macro)
    if bias == 0:
        return None
    side = "buy" if bias > 0 else "sell"
    fibonacci = None
    if require_fibonacci:
        # Lazy import: fibonacci uses confirmed_pivots in this module.
        from .fibonacci import observe_fibonacci
        # The OTE retest must have been observable BEFORE the newest
        # confirmation candle; avoid using the signal candle to satisfy
        # its own prior-confluence condition.
        fibonacci = observe_fibonacci(entry[:-1], side=side)
        if fibonacci is None or not fibonacci.recent_ote_retest:
            return None
    i = len(entry)-1
    candle = entry[i]
    a = atr_at(entry, i)
    if not a:
        return None
    close_break = (candle.close > candle.open and candle.close > max(b.high for b in entry[i-3:i])) if side == "buy" else (
        candle.close < candle.open and candle.close < min(b.low for b in entry[i-3:i]))
    if not close_break or abs(candle.close - candle.open) < .25 * a:
        return None
    for z in reversed(order_blocks(entry)):
        if z.side != side or z.bos_index >= i-1 or i-z.bos_index > 60:
            continue
        # O reteste deve ter ocorrido ANTES do candle de confirmação, recentemente.
        middle = entry[max(z.bos_index+1, i-6):i]
        if not middle:
            continue
        if side == "buy":
            if any(b.close < z.low for b in entry[z.bos_index+1:i]):
                continue
            touched = any(b.low <= z.midpoint and b.high >= z.low for b in middle)
            stop = z.low - .1 * a
        else:
            if any(b.close > z.high for b in entry[z.bos_index+1:i]):
                continue
            touched = any(b.high >= z.midpoint and b.low <= z.high for b in middle)
            stop = z.high + .1 * a
        if not touched:
            continue
        if fibonacci is not None and not fibonacci.ob_overlaps_ote(z.low, z.high):
            continue
        price = candle.close
        distance = abs(price-stop)
        if (side == "buy" and stop >= price) or (side == "sell" and stop <= price):
            continue
        if not .2 * a <= distance <= 5 * a:
            continue
        target = price + rr * distance if side == "buy" else price - rr * distance
        if target <= 0:
            continue
        reason = "BOS + OB com pavios + mitigação 50% + fechamento confirmado"
        if fibonacci is not None:
            reason += " + Fibonacci 61,8–78,6% (filtro experimental)"
        return Signal(side, price, stop, target, rr, z, reason)
    return None
