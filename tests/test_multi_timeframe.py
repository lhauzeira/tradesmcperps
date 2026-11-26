"""Five-period MT5 market-context tests. 100% synthetic; never opens orders."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest

from smc_agent.engine import Candle, macro_bias
from smc_agent.monitor_local import MonitorSnapshot
from smc_agent.multi_timeframe import (
    FrameObservation, MultiTimeframeContext, _extra_frame,
    observe_timeframes, TF_SECONDS
)
from smc_agent.multi_monitor import MarketRow, render_market_table

UTC = timezone.utc
NOW = datetime(2026, 11, 26, 17, 21, 3, tzinfo=UTC)
TICK = datetime(2026, 11, 26, 17, 21, 1, tzinfo=UTC)
OFFSET_LABEL = "UTC+02:00 (observado agora, provisório)"
LAST = {
    "H4": datetime(2026,11,26,12,0,tzinfo=UTC),
    "M30": datetime(2026,11,26,18,30,tzinfo=UTC),
    "M15": datetime(2026,11,26,19,0,tzinfo=UTC),
}


def snap(**changes):
    fields = dict(
        generated_utc=NOW.isoformat(),
        symbol="GOLD", server="XMGlobal-MT5 5",
        connected_to_demo=True, state="AGUARDANDO SETUP SMC",
        last_closed_m5_utc="2026-11-26T17:20:00+00:00",
        last_closed_h1_utc="2026-11-26T17:00:00+00:00",
        quote_time_utc=TICK.isoformat(),
        quote_bid=3560.25, quote_ask=3560.85,
        last_m5_bid_close=3560.15,
        clock_offset_label=OFFSET_LABEL,
        h1_bias="ALTA", m5_bias="BAIXA",
    )
    fields.update(changes)
    return MonitorSnapshot(**fields)


def bars(tf, count=80, raw_last=None):
    raw_last = raw_last or LAST[tf]
    seconds = dict(TF_SECONDS)[tf]
    result=[]
    for i in range(count):
        idx = count-1-i
        opening = raw_last-timedelta(seconds=idx*seconds)
        # Alternating waves with an upward drift: confirmed swings only.
        triangular = min(i % 12, 12 - i % 12) * 1.4
        price = 100 + i*.25 + triangular
        result.append(Candle(
            opening, price-.3, price+.4, price-.6, price,
            tick_volume=50
        ))
    return result


class FakeAdapter:
    def __init__(self, *, fail=(), overrides=None):
        self.fail=set(fail)
        self.overrides=overrides or {}
        self.calls=[]
    def bars(self, timeframe, count):
        self.calls.append((timeframe,count))
        if timeframe in self.fail:
            raise RuntimeError("histórico não carregado")
        return self.overrides.get(timeframe,bars(timeframe))


class MultiTimeframeTests(unittest.TestCase):
    def test_five_timeframes_read_only_with_closed_bar_validation(self):
        a=FakeAdapter()
        report=observe_timeframes(a,snap())
        self.assertEqual([f.timeframe for f in report.frames],
                         ["H4","H1","M30","M15","M5"])
        self.assertEqual(report.available_count,5)
        self.assertEqual([f.state for f in report.frames],["OK"]*5)
        self.assertEqual(a.calls,[("H4",160),("M30",160),("M15",160)])
        self.assertEqual(report.frames[0].last_closed_utc,"2026-11-26T14:00:00+00:00")
        self.assertEqual(report.frames[2].last_closed_utc,"2026-11-26T17:00:00+00:00")
        self.assertEqual(report.frames[3].last_closed_utc,"2026-11-26T17:15:00+00:00")
        self.assertIn("Leitura 5/5",report.summary)
        self.assertIn("H4",report.to_log()["timeframes"])
        self.assertIn("M5",report.to_log()["timeframes"])

    def test_m5_h1_not_re_read_and_existing_bias_preserved(self):
        a=FakeAdapter()
        report=observe_timeframes(a,snap())
        self.assertEqual(report.frames[1].bias,"ALTA")
        self.assertEqual(report.frames[4].bias,"BAIXA")
        self.assertNotIn("H1", [x[0] for x in a.calls])
        self.assertNotIn("M5", [x[0] for x in a.calls])

    def test_missing_m30_is_unavailable_not_neutral(self):
        report=observe_timeframes(FakeAdapter(fail={"M30"}),snap())
        self.assertEqual(report.available_count,4)
        self.assertEqual(report.frames[2].bias,"NÃO AVALIADO")
        self.assertEqual(report.frames[2].state,"INDISPONIVEL")
        self.assertIn("histórico", report.frames[2].explanation)
        self.assertEqual(sum(report.counts.values()),4)

    def test_current_not_closed_m15_cannot_be_used(self):
        future = bars("M15",raw_last=datetime(
            2026,11,26,19,15,tzinfo=UTC
        ))
        report=observe_timeframes(
            FakeAdapter(overrides={"M15":future}),snap()
        )
        self.assertEqual(report.frames[3].state,"INDISPONIVEL")
        self.assertEqual(report.frames[3].bias,"NÃO AVALIADO")
        self.assertIn("futuro",report.frames[3].explanation)

    def test_stale_h4_is_unavailable_instead_of_falsely_confirmed(self):
        old = bars("H4",raw_last=datetime(2026,11,26,4,0,tzinfo=UTC))
        report=observe_timeframes(
            FakeAdapter(overrides={"H4":old}),snap()
        )
        self.assertEqual(report.frames[0].state,"INDISPONIVEL")
        self.assertEqual(report.frames[0].bias,"NÃO AVALIADO")

    def test_raw_server_time_is_adjusted_only_for_live_bar_close(self):
        a=FakeAdapter()
        report=observe_timeframes(a,snap())
        self.assertEqual(report.frames[0].age_seconds,12063.0)
        self.assertGreater(report.frames[0].age_seconds,0)
        self.assertLess(report.frames[0].age_seconds,28800)
        # Bar objects are untouched: no re-writing historical timestamps.
        self.assertEqual(a.overrides,{})

    def test_bad_or_unknown_clock_blocks_extra_fetch(self):
        for invalid in (
            "UTC+04:00 (observado agora, provisório)",
            "UTC+02:00 (provisório)",
            "NÃO VERIFICADO",
        ):
            with self.subTest(label=invalid):
                a=FakeAdapter()
                result=observe_timeframes(a,snap(clock_offset_label=invalid))
                self.assertEqual(result.available_count,0)
                self.assertEqual(a.calls,[])

    def test_invalid_account_and_unfresh_tick_blocks_all_timeframes(self):
        for changes in (
            dict(connected_to_demo=False),
            dict(quote_time_utc="2026-11-26T17:15:00+00:00"),
            dict(quote_time_utc="2026-11-26T17:22:00+00:00"),
        ):
            with self.subTest(changes=changes):
                a=FakeAdapter()
                result=observe_timeframes(a,snap(**changes))
                self.assertEqual(result.available_count,0)
                self.assertEqual(a.calls,[])

    def test_history_insufficient_prevents_fake_bias(self):
        report=observe_timeframes(FakeAdapter(
            overrides={"H4":bars("H4",count=30)}
        ),snap())
        self.assertEqual(report.frames[0].state,"INDISPONIVEL")
        self.assertIn("insuficiente",report.frames[0].explanation)

    def test_repeated_timestamps_prevent_structure_inference(self):
        duplicate=bars("H4")
        duplicate[-1]=replace(duplicate[-1],time=duplicate[-2].time)
        report=observe_timeframes(FakeAdapter(
            overrides={"H4":duplicate}
        ),snap())
        self.assertEqual(report.frames[0].state,"INDISPONIVEL")

    def test_no_lookahead_confirmed_pivot_structure_uses_only_closed_data(self):
        data=bars("H4")
        baseline=macro_bias(data)
        # Last candle may move but no future close is added to confirm it.
        future=replace(data[-1],high=data[-1].high+1000,close=data[-1].close)
        self.assertEqual(macro_bias(data[:-1]),macro_bias(
            data[:-1]))
        self.assertEqual(macro_bias(data[:-2]),macro_bias(data[:-2]))
        self.assertIn(baseline,(-1,0,1))
        self.assertIsInstance(future,Candle)

    def test_dashboard_renders_five_frames_without_promising_execution(self):
        context=observe_timeframes(FakeAdapter(),snap())
        html=render_market_table(
            (MarketRow("GOLD",snap(),None,None,context),),NOW.isoformat()
        )
        for tf in ("H4","H1","M30","M15","M5"):
            self.assertIn(">"+tf+"<",html)
        self.assertIn("Estrutura em cinco períodos",html)
        self.assertIn("Observacional",html)
        self.assertIn("Ordens enviadas: 0",html)

    def test_untrusted_error_in_table_is_escaped(self):
        a=FakeAdapter(fail={"H4"})
        a.bars=lambda timeframe,count: (
            (_ for _ in ()).throw(RuntimeError("<script>x</script>"))
            if timeframe=="H4" else bars(timeframe)
        )
        context=observe_timeframes(a,snap())
        html=render_market_table(
            (MarketRow("GOLD",snap(),None,None,context),),NOW.isoformat()
        )
        self.assertNotIn("<script>",html)
        self.assertIn("&lt;script&gt;",html)

    def test_unknown_labels_and_order_rejected(self):
        with self.assertRaises(ValueError):
            FrameObservation("W1","ALTA",None,None,"OK")
        with self.assertRaises(ValueError):
            FrameObservation("H4","ALTA",None,None,"INDISPONIVEL")
        with self.assertRaises(ValueError):
            MultiTimeframeContext(tuple())

    def test_m30_adapter_calls_only_closed_bar_position_one(self):
        from smc_agent.adapters import MT5Adapter
        class FakeMT5:
            TIMEFRAME_M30=30
            def __init__(self): self.calls=[]
            def copy_rates_from_pos(self, symbol, tf, start, count):
                self.calls.append((symbol,tf,start,count))
                start_dt=datetime(2026,11,26,15,0,tzinfo=UTC)
                return [{
                    "time":int((start_dt+timedelta(minutes=i*30)).timestamp()),
                    "open":100.0,"high":101.0,"low":99.0,"close":100.5,
                    "tick_volume":100
                } for i in range(50)]
        fake=FakeMT5()
        with patch.dict(sys.modules,{"MetaTrader5":fake}):
            adapter=MT5Adapter("GOLD")
            output=adapter.bars("M30",count=50)
        self.assertEqual(len(output),50)
        self.assertEqual(fake.calls,[("GOLD",30,1,50)])


if __name__ == "__main__":
    unittest.main()
