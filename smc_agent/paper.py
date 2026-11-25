"""Deterministic PAPER-only scenario replay for the XM GOLD contract snapshot.

Never place an order. A "paper fill" below is a model assumption, not evidence
of a trade on the broker. No historical profits are claimed.

Supported: marketable PAPER entry at the open of the next complete quote bar.
The published plan is used only for direction, target, stop and drift checks.
We refuse to infer execution when sessions, data continuity or event ordering
are uncertain. Price samples must represent an independently valid bid/ask
feed for the exact venue/instrument, not approximations from the other side.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from typing import Mapping

from .lifecycle import PublishedSignal, _aware
from .quotes import QuoteHistory
from .xm_gold_risk import GoldContractSnapshot, XM_GOLD_DEMO_SNAPSHOT, D


@dataclass(frozen=True)
class SessionWindow:
    """Half-open minute interval in the verified historical SERVER clock."""
    start_minute: int
    end_minute: int

    def __post_init__(self):
        if not (isinstance(self.start_minute, int)
                and isinstance(self.end_minute, int)
                and 0 <= self.start_minute < self.end_minute <= 1440):
            raise ValueError("Session must fit a single day with positive length")


@dataclass(frozen=True)
class TradingSessions:
    """Explicit historical server offset and session coverage.

    Any unknown weekday has value None, rather than being assumed open.
    Empty tuple means independently verified closed for that weekday.
    """
    verified_server_utc_offset_minutes: int | None
    weekdays: Mapping[int, tuple[SessionWindow, ...] | None]

    def __post_init__(self):
        offset = self.verified_server_utc_offset_minutes
        if offset is not None and (
            type(offset) is not int or not -720 <= offset <= 840
        ):
            raise ValueError("Unverified or invalid server offset")
        if any(type(k) is not int or k < 0 or k > 6 for k in self.weekdays):
            raise ValueError("Weekdays must be 0=Mon through 6=Sun")
        for windows in self.weekdays.values():
            if windows is None:
                continue
            previous_end = 0
            for window in windows:
                if not isinstance(window, SessionWindow):
                    raise ValueError("Invalid session window")
                if window.start_minute < previous_end:
                    raise ValueError("Unsorted or overlapping trading sessions")
                previous_end = window.end_minute

    def status(self, opened_at: datetime, closed_at: datetime) -> str:
        _aware(opened_at, "opened_at")
        _aware(closed_at, "closed_at")
        if opened_at >= closed_at:
            raise ValueError("Invalid candle interval")
        minutes = self.verified_server_utc_offset_minutes
        if minutes is None:
            return "UNVERIFIED"
        offset = timezone(timedelta(minutes=minutes))
        opening = opened_at.astimezone(offset)
        closing = closed_at.astimezone(offset)
        if opening.date() != closing.date():
            return "UNVERIFIED"
        windows = self.weekdays.get(opening.weekday())
        if windows is None:
            return "UNVERIFIED"
        start = opening.hour * 60 + opening.minute + (
            opening.second + opening.microsecond / 1_000_000
        ) / 60
        finish = closing.hour * 60 + closing.minute + (
            closing.second + closing.microsecond / 1_000_000
        ) / 60
        if any(w.start_minute <= start and finish <= w.end_minute for w in windows):
            return "OPEN"
        return "CLOSED"


@dataclass(frozen=True)
class PaperAssumptions:
    """Costs/limits are explicitly hypothetical and supplied by caller."""
    risk_budget_usd: Decimal
    extra_loss_reserve_usd: Decimal
    commission_roundtrip_usd_per_lot: Decimal
    slippage_each_side_price: Decimal
    max_entry_drift_price: Decimal
    max_open_spread_pct: Decimal
    max_entry_wait_seconds: int = 600
    quote_bar_seconds: int = 300
    max_bars: int = 48

    def __post_init__(self):
        for name in ("risk_budget_usd", "extra_loss_reserve_usd",
                     "commission_roundtrip_usd_per_lot", "slippage_each_side_price",
                     "max_entry_drift_price", "max_open_spread_pct"):
            value = D(getattr(self, name), name)
            if value < 0:
                raise ValueError(f"{name} must be nonnegative")
        if D(self.risk_budget_usd, "risk_budget_usd") <= 0:
            raise ValueError("Risk budget must be positive")
        if not (0 < D(self.max_open_spread_pct, "max_open_spread_pct") <= 10):
            raise ValueError("Invalid maximum open spread percent")
        if (type(self.max_entry_wait_seconds) is not int
                or self.max_entry_wait_seconds <= 0):
            raise ValueError("Invalid maximum entry wait")
        if (type(self.quote_bar_seconds) is not int or
                self.quote_bar_seconds <= 0):
            raise ValueError("Invalid candle duration")
        if type(self.max_bars) is not int or not 1 <= self.max_bars <= 10_000:
            raise ValueError("Invalid observation horizon")


@dataclass(frozen=True)
class PaperResult:
    signal_id: str
    status: str
    bars_examined: int
    paper_entry_price: Decimal | None = None
    paper_exit_price: Decimal | None = None
    paper_lots: Decimal | None = None
    modeled_gross_usd: Decimal | None = None
    modeled_net_usd: Decimal | None = None
    modeled_fees_usd: Decimal | None = None
    note: str = ("HYPOTHETICAL ONLY: not a broker fill or realized profit.")

    @property
    def broker_fills_verified(self):
        return False

    @property
    def orders_sent(self):
        return 0


def replay_market_next_open(
    signal: PublishedSignal, history: QuoteHistory, *,
    sessions: TradingSessions, assumptions: PaperAssumptions,
    as_of: datetime,
    contract: GoldContractSnapshot = XM_GOLD_DEMO_SNAPSHOT,
) -> PaperResult:
    """Conservative no-network paper replay with explicit stop/TP uncertainty.

    Unknown sessions and history gaps prevent a modeled outcome. The model
    uses next future quote bar open, so it does not reconstruct a limit order
    or pretend that the signal's printed entry was actually achieved.
    """
    _aware(as_of, "as_of")
    if as_of < signal.published_at:
        raise ValueError("Observation cutoff precedes signal")
    if (signal.venue, signal.symbol) != (history.venue, history.symbol):
        raise ValueError("Feed/signal venue mismatch")
    if (signal.venue, signal.symbol) != (contract.venue, contract.symbol):
        raise ValueError("Cannot apply unrelated broker contract to feed")
    if not history.origin:
        raise ValueError("Quote provenance required")

    candidate = [
        b for b in history.bars
        if b.opened_at > signal.published_at and b.closed_at <= as_of
    ][:assumptions.max_bars]
    if not candidate:
        return PaperResult(signal.signal_id, "NO_POST_PUBLICATION_DATA", 0)

    entry_bar = candidate[0]
    latency = (entry_bar.opened_at - signal.published_at).total_seconds()
    if latency > assumptions.max_entry_wait_seconds:
        return PaperResult(signal.signal_id, "NO_ENTRY_STALE_QUOTES", 0)
    if latency <= 0:
        raise AssertionError("Next quote bar cannot precede publication")

    lots = entry_price = None
    prev = None
    for n, bar in enumerate(candidate, start=1):
        if int((bar.closed_at - bar.opened_at).total_seconds()) != assumptions.quote_bar_seconds:
            return PaperResult(signal.signal_id, "CANDLE_DURATION_UNVERIFIED", n-1,
                               paper_entry_price=entry_price, paper_lots=lots)
        if prev is not None and bar.opened_at != prev.closed_at:
            return PaperResult(signal.signal_id, "QUOTE_GAP_UNRESOLVED", n-1,
                               paper_entry_price=entry_price, paper_lots=lots)
        window_status = sessions.status(bar.opened_at, bar.closed_at)
        if window_status != "OPEN":
            return PaperResult(
                signal.signal_id,
                "SESSION_UNVERIFIED" if window_status == "UNVERIFIED"
                else ("NO_ENTRY_SESSION_CLOSED" if lots is None
                      else "SESSION_CLOSED_AFTER_PAPER_ENTRY"),
                n-1, paper_entry_price=entry_price, paper_lots=lots,
                note="No permitted inference when session or timezone rules are unresolved.")
        spread = D(bar.ask_open, "ask_open") - D(bar.bid_open, "bid_open")
        mid = (D(bar.ask_open, "ask_open") + D(bar.bid_open, "bid_open")) / 2
        spread_pct = spread / mid * 100
        if spread_pct > D(assumptions.max_open_spread_pct, "max_open_spread_pct"):
            return PaperResult(
                signal.signal_id,
                "NO_ENTRY_WIDE_SPREAD" if lots is None else "SPREAD_VETO_AFTER_PAPER_ENTRY",
                n-1, paper_entry_price=entry_price, paper_lots=lots)

        if signal.side == "buy":
            opening = D(bar.ask_open, "ask_open")
            exit_open = D(bar.bid_open, "bid_open")
            hi, lo = D(bar.bid_high, "bid_high"), D(bar.bid_low, "bid_low")
            direction = Decimal("1")
        else:
            opening = D(bar.bid_open, "bid_open")
            exit_open = D(bar.ask_open, "ask_open")
            hi, lo = D(bar.ask_high, "ask_high"), D(bar.ask_low, "ask_low")
            direction = Decimal("-1")
        entry_plan = D(signal.entry, "signal.entry")
        stop, target = D(signal.stop, "signal.stop"), D(signal.target, "signal.target")
        slippage = D(assumptions.slippage_each_side_price, "slippage_each_side_price")
        commission = D(assumptions.commission_roundtrip_usd_per_lot, "commission")

        if lots is None:
            # There was NO earlier simulated order; position is opened only
            # after checking session, latency, drift, spread and risk.
            entry_price = opening + slippage * direction
            if abs(entry_price - entry_plan) > D(assumptions.max_entry_drift_price, "drift"):
                return PaperResult(signal.signal_id, "NO_ENTRY_PRICE_DRIFT", n-1)
            if ((signal.side == "buy" and not stop < entry_price < target) or
                (signal.side == "sell" and not target < entry_price < stop)):
                return PaperResult(signal.signal_id, "NO_ENTRY_INVALID_QUOTE", n-1)
            # A spread can put the *exit* quote beyond the stop even though
            # the simulated entry quote is inside the price boundaries.
            # Do not fabricate an immediately viable trade in that case.
            if ((signal.side == "buy" and not stop < exit_open < target) or
                (signal.side == "sell" and not target < exit_open < stop)):
                return PaperResult(signal.signal_id, "NO_ENTRY_EXIT_QUOTE_OUTSIDE_LEVELS", n-1)
            # Only the hypothetical STOP scenario + explicit reserve is used
            # for sizing; no slippage guarantee or broker margin available.
            risk_per_lot = (
                ((abs(entry_price-stop)+slippage) / contract.tick_size)
                * contract.tick_value_usd_per_lot + commission
            )
            funds = (D(assumptions.risk_budget_usd, "risk_budget") -
                     D(assumptions.extra_loss_reserve_usd, "reserve"))
            if funds <= 0:
                return PaperResult(signal.signal_id, "NO_TRADE_RISK_CAP", n-1)
            steps = ((funds / risk_per_lot) / contract.lot_step).to_integral_value(
                rounding=ROUND_FLOOR)
            lots = min(contract.lot_max, steps*contract.lot_step)
            if lots < contract.lot_min:
                return PaperResult(signal.signal_id, "NO_TRADE_MIN_LOT_RISK", n-1)
            contract.valid_volume(lots)
            if (risk_per_lot*lots + D(assumptions.extra_loss_reserve_usd, "reserve")
                    > D(assumptions.risk_budget_usd, "budget")):
                raise AssertionError("Risk cap violated in paper sizing")

        else:
            # An exit *gap* could bypass stop or target; price and order type
            # cannot be reconstructed from a closed OHLC interval.
            if ((signal.side == "buy" and (exit_open < stop or exit_open > target))
                or (signal.side == "sell" and (exit_open > stop or exit_open < target))):
                return PaperResult(signal.signal_id, "GAP_EXIT_UNPRICED", n,
                                   paper_entry_price=entry_price, paper_lots=lots)
        stop_touch = lo <= stop
        target_touch = hi >= target if signal.side == "buy" else lo <= target
        if signal.side == "sell":
            stop_touch = hi >= stop

        if stop_touch and target_touch:
            return PaperResult(signal.signal_id, "AMBIGUOUS_INTRA_BAR", n,
                               paper_entry_price=entry_price, paper_lots=lots)
        if stop_touch or target_touch:
            base_exit = stop if stop_touch else target
            exit_price = base_exit - direction*slippage
            gross = (exit_price-entry_price) * direction / contract.tick_size * (
                contract.tick_value_usd_per_lot * lots)
            fees = commission * lots
            return PaperResult(
                signal.signal_id,
                "PAPER_STOP_MODEL" if stop_touch else "PAPER_TARGET_MODEL", n,
                paper_entry_price=entry_price, paper_exit_price=exit_price,
                paper_lots=lots, modeled_gross_usd=gross,
                modeled_net_usd=gross-fees, modeled_fees_usd=fees,
                note="Model price touches + assumed execution/slippage; no verified broker fill.")
        prev = bar

    return PaperResult(signal.signal_id, "PAPER_OPEN_UNRESOLVED", len(candidate),
                       paper_entry_price=entry_price, paper_lots=lots)
