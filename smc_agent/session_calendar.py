"""Broker-specific session/holiday schedule RESEARCH, fail-closed.

This is NOT a calendar of actual XM opening hours. Real schedule rows must
be verified independently against the broker's authoritative instrument-
specific schedule, including holidays, early closures and DST transitions.

Only explicit UTC windows and explicitly covered UTC dates can contribute
to a pretrade SESSION observation. Weekday assumptions, symbol trade_mode
and recent ticks are NEVER accepted as evidence of an open broker session.

This module never grants order permission. No order_send, network, MT5.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


def _utc(dt: datetime, field: str) -> datetime:
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field} must have an explicit time zone")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class UTCWindow:
    start: datetime
    end: datetime

    def __post_init__(self):
        a, b = _utc(self.start, "start"), _utc(self.end, "end")
        if not a < b or b-a > timedelta(days=1):
            raise ValueError("Invalid UTC session duration")
        if a.date() > b.date():
            raise ValueError("Session dates are not chronological")

    def includes(self, instant: datetime) -> bool:
        stamp = _utc(instant, "instant")
        return _utc(self.start, "start") <= stamp < _utc(self.end, "end")


@dataclass(frozen=True)
class BrokerDay:
    symbol: str
    utc_date: date
    status: str
    windows: tuple[UTCWindow, ...]
    source_reference: str
    confirmed_at: datetime
    expires_at: datetime

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("Instrument symbol required")
        if type(self.utc_date) is not date:
            raise ValueError("UTC calendar date required")
        if self.status not in ("REGULAR", "SPECIAL", "CLOSED"):
            raise ValueError("Invalid broker day status")
        if not isinstance(self.windows, tuple):
            raise ValueError("Session windows must be immutable")
        if self.status == "CLOSED" and self.windows:
            raise ValueError("A closed day cannot have trading windows")
        if self.status != "CLOSED" and not self.windows:
            raise ValueError("A tradable day must specify explicit UTC windows")
        if not isinstance(self.source_reference, str) or len(self.source_reference.strip()) < 8:
            raise ValueError("Broker-specific session evidence required")
        checked = _utc(self.confirmed_at, "confirmed_at")
        expires = _utc(self.expires_at, "expires_at")
        if checked >= expires:
            raise ValueError("Schedule evidence must have a valid freshness window")
        preceding = None
        for window in self.windows:
            if not isinstance(window, UTCWindow):
                raise ValueError("Invalid UTCWindow")
            a, b = _utc(window.start, "start"), _utc(window.end, "end")
            if a.date() != self.utc_date:
                raise ValueError("Session must start on the explicitly covered UTC day")
            if preceding is not None and a < preceding:
                raise ValueError("Session windows cannot overlap")
            preceding = b


@dataclass(frozen=True)
class BrokerSessionObservation:
    symbol: str
    time_utc: datetime
    status: str
    schedule_evidence: str | None
    current_window: bool
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.can_submit_orders:
            raise ValueError("Schedule observation never permits broker orders")


class SessionCalendar:
    """Explicit per-symbol UTC coverage: unknown date never means open."""

    def __init__(self, rows: tuple[BrokerDay, ...] = ()):
        if not isinstance(rows, tuple):
            raise ValueError("Immutable rows required")
        self._by_day = {}
        for row in rows:
            if not isinstance(row, BrokerDay):
                raise ValueError("Invalid broker session row")
            key = (row.symbol, row.utc_date)
            if key in self._by_day:
                raise ValueError("Duplicated symbol/date schedule")
            self._by_day[key] = row

    def evaluate(self, symbol: str, *, now: datetime) -> BrokerSessionObservation:
        moment = _utc(now, "now")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("Instrument required")
        day = moment.date()

        def report(status: str, source: str | None = None,
                   candidate: bool = False) -> BrokerSessionObservation:
            return BrokerSessionObservation(
                symbol, moment, status, source, candidate
            )

        today = self._by_day.get((symbol, day))
        previous = self._by_day.get((symbol, day-timedelta(days=1)))
        # A prior day's overnight session cannot bypass an unknown day,
        # today's special closure or today's expired verified schedule.
        if today is None:
            return report("DATA_SEM_COBERTURA")
        if not _utc(today.confirmed_at,"confirmed_at") <= moment < _utc(
                today.expires_at,"expires_at"):
            return report("EVIDENCIA_DE_SESSAO_EXPIRADA_OU_FUTURA")
        if today.status == "CLOSED":
            return report("FECHAMENTO_PROGRAMADO",today.source_reference)
        # Overnight windows may extend into today's UTC date, but both
        # UTC dates must be covered and today must not be CLOSED.
        applicable = []
        for row in (previous, today):
            if row is None:
                continue
            approved = _utc(row.confirmed_at,"confirmed_at")
            expires = _utc(row.expires_at,"expires_at")
            if not approved <= moment < expires:
                continue
            if any(window.includes(moment) for window in row.windows):
                applicable.append(row)
        if applicable:
            row = applicable[0]
            return report(
                "JANELA_PROGRAMADA_NAO_AUTORIZADA", row.source_reference, True
            )
        return report("FORA_DA_JANELA_PROGRAMADA",today.source_reference)


def fictional_session_demo() -> str:
    """Entirely invented schedule. It MUST NEVER be used for actual trading."""
    instant = datetime(2026, 11, 26, 18, 10, tzinfo=timezone.utc)
    day = BrokerDay(
        symbol="ATIVO_FICTICIO",
        utc_date=instant.date(), status="SPECIAL",
        windows=(UTCWindow(
            instant-timedelta(minutes=30), instant+timedelta(minutes=30)
        ),),
        source_reference="TEST_ONLY_SCHEDULE_NOT_XM",
        confirmed_at=instant-timedelta(hours=1),
        expires_at=instant+timedelta(hours=1),
    )
    result=SessionCalendar((day,)).evaluate("ATIVO_FICTICIO",now=instant)
    return (
        "CALENDARIO INTEIRAMENTE FICTICIO (NAO REPRESENTA A XM)\n"
        f"Estado: {result.status}\n"
        f"Candidato a janela: {result.current_window}\n"
        "HABILITACAO DE ORDENS: FALSO. ZERO ORDENS ENVIADAS."
    )


if __name__=="__main__":
    print(fictional_session_demo())
