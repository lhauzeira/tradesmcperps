"""MT5 GOLD session metadata observed from a USER-PROVIDED SCREENSHOT.

A *current* specification screenshot is not a verified historical session
calendar and does not establish the timezone of the MT5 tick export.

No live API calls, broker account access or orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from .paper import SessionWindow, TradingSessions


def _window(hours_minutes: str) -> int:
    """Hours/minutes as displayed by MT5; no timezone implied."""
    hour, minute = map(int, hours_minutes.split(":"))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Invalid displayed HH:MM time")
    return 60 * hour + minute


@dataclass(frozen=True)
class DisplayedDay:
    """A session as shown by MT5, not an authorization for historical trading."""
    quote_open: str | None
    quote_close: str | None
    trade_open: str | None
    trade_close: str | None

    def __post_init__(self):
        fields = (self.quote_open, self.quote_close,
                  self.trade_open, self.trade_close)
        if all(value is None for value in fields):
            return
        if any(value is None for value in fields):
            raise ValueError("Partial displayed session without full time range")
        q0 = _window(self.quote_open)
        q1 = _window(self.quote_close)
        t0 = _window(self.trade_open)
        t1 = _window(self.trade_close)
        if not (q0 < q1 and t0 < t1 and q0 <= t0 < t1 <= q1):
            raise ValueError("Trading session must fit within quoted session")

    def research_trade_window(self) -> SessionWindow | None:
        if self.trade_open is None:
            return None
        # Conservative *exclusive* end boundary: do not assume that all
        # seconds in the final displayed minute allow trading.
        return SessionWindow(_window(self.trade_open), _window(self.trade_close))


@dataclass(frozen=True)
class XMGoldDisplayedSchedule:
    venue: str
    symbol: str
    screenshot_received_on: date
    observed_days: Mapping[int, DisplayedDay]

    def __post_init__(self):
        if not self.venue or not self.symbol:
            raise ValueError("Broker identity and native instrument required")
        if set(self.observed_days) != set(range(7)):
            raise ValueError("A complete seven-weekday screenshot reading is required")
        if not all(isinstance(x, DisplayedDay) for x in self.observed_days.values()):
            raise ValueError("Invalid weekly schedule records")

    def as_unverified_paper_calendar(self) -> TradingSessions:
        """Preserve shown trading windows but block every simulated outcome.

        No historical GMT offset is inferred from screen information.
        Even when weekdays are shown, paper replay must return
        SESSION_UNVERIFIED until historical validity and timezone are
        checked separately.
        """
        windows = {}
        for day, session in self.observed_days.items():
            w = session.research_trade_window()
            windows[day] = () if w is None else (w,)
        return TradingSessions(
            verified_server_utc_offset_minutes=None, weekdays=windows
        )


# Weekdays follow Python's convention: Monday=0 ... Sunday=6.
# Specific to the GOLD instrument in XMGlobal-MT5 5 demo snapshot.
# Screenshot sent 2026-11-25; NOT proven applicable to June or future dates.
XM_GOLD_DISPLAYED = XMGoldDisplayedSchedule(
    venue="XMGlobal-MT5 5 (demo)",
    symbol="GOLD",
    screenshot_received_on=date(2026, 11, 25),
    observed_days={
        0: DisplayedDay("01:00", "23:59", "01:02", "23:58"),
        1: DisplayedDay("01:00", "23:59", "01:02", "23:58"),
        2: DisplayedDay("01:00", "23:59", "01:02", "23:58"),
        3: DisplayedDay("01:00", "23:59", "01:02", "23:58"),
        4: DisplayedDay("01:00", "23:58", "01:02", "23:58"),
        5: DisplayedDay(None, None, None, None),
        6: DisplayedDay(None, None, None, None),
    },
)


def schedule_snapshot() -> dict:
    """Private-data-free display summary used by the CI offline demo."""
    items = {}
    for day, value in sorted(XM_GOLD_DISPLAYED.observed_days.items()):
        items[str(day)] = {
            "quote": None if value.quote_open is None
            else f"{value.quote_open}-{value.quote_close}",
            "trading": None if value.trade_open is None
            else f"{value.trade_open}-{value.trade_close}",
        }
    return {
        "source": "MT5_GOLD_USER_SCREENSHOT_NOV_25_2026",
        "venue": XM_GOLD_DISPLAYED.venue,
        "symbol": XM_GOLD_DISPLAYED.symbol,
        "display_clock_utc_offset": "UNVERIFIED",
        "historical_validity": "UNVERIFIED",
        "sessions_by_weekday_monday_0": items,
        "historical_paper_trading_allowed": False,
        "broker_orders_sent": 0,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(schedule_snapshot(), indent=2, ensure_ascii=False))
