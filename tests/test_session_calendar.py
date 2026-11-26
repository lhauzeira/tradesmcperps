"""Explicit UTC broker session schedule tests — ALL schedules fictitious."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import subprocess
import sys
import unittest

from smc_agent.session_calendar import (
    UTCWindow, BrokerDay, SessionCalendar, fictional_session_demo
)

UTC = timezone.utc
T = datetime(2026,11,26,18,0,tzinfo=UTC)
SOURCE = "FICTITIOUS_TEST_NOT_XM"


def window(start=17, end=20, *, day=26):
    a=datetime(2026,11,day,start,tzinfo=UTC)
    b=datetime(2026,11,day,end,tzinfo=UTC)
    return UTCWindow(a,b)


def day(symbol="GOLD",*, utc_date=date(2026,11,26),
        status="REGULAR", windows=None, issued=None, expires=None):
    if windows is None:
        windows = () if status=="CLOSED" else (window(),)
    return BrokerDay(
        symbol=symbol,utc_date=utc_date,status=status,
        windows=windows,source_reference=SOURCE,
        confirmed_at=issued or T-timedelta(days=1),
        expires_at=expires or T+timedelta(days=1),
    )


class ExplicitBrokerSessionsTests(unittest.TestCase):
    def test_explicit_session_window_is_candidate_never_order_permission(self):
        report=SessionCalendar((day(),)).evaluate("GOLD",now=T)
        self.assertEqual(report.status,"JANELA_PROGRAMADA_NAO_AUTORIZADA")
        self.assertTrue(report.current_window)
        self.assertFalse(report.can_submit_orders)
        self.assertEqual(report.schedule_evidence,SOURCE)

    def test_no_unverified_weekday_fallback(self):
        report=SessionCalendar().evaluate("GOLD",now=T)
        self.assertEqual(report.status,"DATA_SEM_COBERTURA")
        self.assertFalse(report.current_window)

    def test_symbol_cannot_inherit_another_symbols_session(self):
        report=SessionCalendar((day("US100Cash"),)).evaluate("GOLD",now=T)
        self.assertEqual(report.status,"DATA_SEM_COBERTURA")
        self.assertFalse(report.can_submit_orders)

    def test_explicit_holiday_closure_overrides_positive_tick_assumptions(self):
        report=SessionCalendar((day(status="CLOSED"),)).evaluate("GOLD",now=T)
        self.assertEqual(report.status,"FECHAMENTO_PROGRAMADO")
        self.assertFalse(report.current_window)

    def test_special_early_close_is_not_open_after_last_window(self):
        special=day(status="SPECIAL",windows=(window(start=15,end=17),))
        report=SessionCalendar((special,)).evaluate("GOLD",now=T)
        self.assertEqual(report.status,"FORA_DA_JANELA_PROGRAMADA")
        self.assertFalse(report.current_window)

    def test_earlier_included_last_open_close_boundary_rules(self):
        session=day()
        cal=SessionCalendar((session,))
        self.assertTrue(cal.evaluate("GOLD",now=T-timedelta(minutes=1)).current_window)
        at_end=datetime(2026,11,26,20,0,tzinfo=UTC)
        self.assertFalse(cal.evaluate("GOLD",now=at_end).current_window)

    def test_expired_schedule_blocks_even_during_programmed_window(self):
        expired=day(expires=T-timedelta(seconds=1))
        report=SessionCalendar((expired,)).evaluate("GOLD",now=T)
        self.assertEqual(report.status,"EVIDENCIA_DE_SESSAO_EXPIRADA_OU_FUTURA")

    def test_schedule_confirmation_in_future_is_unverified(self):
        future=day(issued=T+timedelta(seconds=1))
        report=SessionCalendar((future,)).evaluate("GOLD",now=T)
        self.assertEqual(report.status,"EVIDENCIA_DE_SESSAO_EXPIRADA_OU_FUTURA")

    def test_cross_midnight_window_needs_coverage_on_both_days(self):
        previous=day(
            utc_date=date(2026,11,25),status="SPECIAL",
            windows=(UTCWindow(
                datetime(2026,11,25,23,0,tzinfo=UTC),
                datetime(2026,11,26,2,0,tzinfo=UTC),
            ),),
        )
        early=datetime(2026,11,26,1,0,tzinfo=UTC)
        without_today=SessionCalendar((previous,)).evaluate("GOLD",now=early)
        self.assertEqual(without_today.status,"DATA_SEM_COBERTURA")
        today=day(status="SPECIAL",windows=(window(start=17,end=18),))
        report=SessionCalendar((previous,today)).evaluate("GOLD",now=early)
        self.assertEqual(report.status,"JANELA_PROGRAMADA_NAO_AUTORIZADA")
        self.assertFalse(report.can_submit_orders)

    def test_closed_today_overrides_previous_overnight_session(self):
        previous=day(
            utc_date=date(2026,11,25),status="SPECIAL",
            windows=(UTCWindow(
                datetime(2026,11,25,23,0,tzinfo=UTC),
                datetime(2026,11,26,2,0,tzinfo=UTC),
            ),),
        )
        today=day(status="CLOSED")
        report=SessionCalendar((previous,today)).evaluate(
            "GOLD",now=datetime(2026,11,26,1,0,tzinfo=UTC)
        )
        self.assertEqual(report.status,"FECHAMENTO_PROGRAMADO")

    def test_invalid_duplicated_symbol_date_rejected(self):
        with self.assertRaisesRegex(ValueError,"Duplicated"):
            SessionCalendar((day(),day()))

    def test_overlapping_and_out_of_order_windows_rejected(self):
        with self.assertRaisesRegex(ValueError,"overlap"):
            day(windows=(window(17,19),window(18,20)))
        with self.assertRaises(ValueError):
            day(windows=(window(19,20),window(17,18)))

    def test_missing_source_and_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            replace(day(),source_reference="")
        with self.assertRaises(ValueError):
            replace(day(),status="UNKNOWN")
        with self.assertRaises(ValueError):
            replace(day(),status="CLOSED",windows=(window(),))

    def test_closed_and_open_day_incompatible_windows(self):
        with self.assertRaises(ValueError):
            day(status="REGULAR",windows=())
        with self.assertRaises(ValueError):
            day(status="CLOSED",windows=(window(),))

    def test_naive_and_reversed_times_refused(self):
        with self.assertRaises(ValueError):
            UTCWindow(datetime(2026,11,26,17),T)
        with self.assertRaises(ValueError):
            UTCWindow(T,T)
        with self.assertRaises(ValueError):
            SessionCalendar().evaluate("GOLD",now=datetime(2026,11,26,18))
        with self.assertRaises(ValueError):
            replace(day(),expires_at=T-timedelta(days=3))

    def test_source_must_reapprove_new_dates_after_dst_transition(self):
        # No weekday or DST assumptions: explicit UTC coverage only.
        cal=SessionCalendar((day(),))
        after_dst=T+timedelta(days=30)
        result=cal.evaluate("GOLD",now=after_dst)
        self.assertEqual(result.status,"DATA_SEM_COBERTURA")

    def test_fictional_cli_does_not_fetch_live_broker_hours(self):
        msg=fictional_session_demo()
        self.assertIn("INTEIRAMENTE FICTICIO",msg)
        self.assertIn("ORDENS ENVIADAS",msg)
        r=subprocess.run(
            [sys.executable,"-m","smc_agent.session_calendar"],
            text=True,capture_output=True,timeout=10
        )
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("HABILITACAO DE ORDENS: FALSO",r.stdout)


if __name__=="__main__":
    unittest.main()
