"""Purely synthetic bid/ask order-state tests, without brokerage calls."""
from datetime import datetime, timedelta, timezone
import subprocess
import sys
import unittest

from smc_agent.paper_execution import (
    PaperIntent, PaperQuote, PaperPosition, PaperOutcome,
    SyntheticPaperBook, synthetic_demo,
)

T = datetime(2026, 1, 5, 14, tzinfo=timezone.utc)


def quote(*, seconds=0, bid=100.0, ask=100.2, symbol="GOLD"):
    return PaperQuote(symbol, T+timedelta(seconds=seconds), bid, ask)


class SyntheticPaperLifecycleTests(unittest.TestCase):
    def test_open_buy_at_ask_then_close_at_bid_target(self):
        book = SyntheticPaperBook()
        pos = book.open_hypothetical(
            PaperIntent("buy-1","GOLD","buy",stop=99.0,target=102.0),
            quote()
        )
        self.assertEqual(pos.entry_price,100.2)
        self.assertEqual(len(book.open_positions),1)
        out = book.observe("buy-1",quote(seconds=1,bid=102.1,ask=102.3))
        self.assertEqual(out.outcome,"ALVO_OBSERVADO")
        self.assertEqual(out.observed_exit_price,102.1)
        self.assertAlmostEqual(out.pnl_price_units,1.9)
        self.assertEqual(len(book.open_positions),0)

    def test_buy_stop_at_observed_price_not_assumed_stop_fill(self):
        book = SyntheticPaperBook()
        book.open_hypothetical(
            PaperIntent("buy-2","GOLD","buy",stop=99,target=102),quote()
        )
        out = book.observe("buy-2",quote(seconds=1,bid=98.4,ask=98.6))
        self.assertEqual(out.outcome,"STOP_OBSERVADO")
        self.assertEqual(out.observed_exit_price,98.4)
        self.assertAlmostEqual(out.pnl_price_units,-1.8)

    def test_sell_enters_bid_and_exits_ask(self):
        book = SyntheticPaperBook()
        pos = book.open_hypothetical(
            PaperIntent("sell-1","US100Cash","sell",stop=105,target=95),
            PaperQuote("US100Cash",T,bid=100.0,ask=100.5)
        )
        self.assertEqual(pos.entry_price,100)
        out = book.observe("sell-1",PaperQuote(
            "US100Cash",T+timedelta(seconds=1),bid=94.5,ask=95))
        self.assertEqual(out.outcome,"ALVO_OBSERVADO")
        self.assertAlmostEqual(out.pnl_price_units,5)

    def test_sell_stop_gap_worsens_observed_result(self):
        book = SyntheticPaperBook()
        book.open_hypothetical(
            PaperIntent("sell-stop","GOLD","sell",stop=101,target=95),quote()
        )
        out=book.observe("sell-stop",quote(seconds=1,bid=102,ask=102.2))
        self.assertEqual(out.outcome,"STOP_OBSERVADO")
        self.assertAlmostEqual(out.pnl_price_units,-2.2)

    def test_insufficient_quote_coverage_is_inconclusive_not_win(self):
        book = SyntheticPaperBook(max_quote_gap_seconds=2)
        book.open_hypothetical(
            PaperIntent("gapped","GOLD","buy",stop=99,target=102),quote()
        )
        out=book.observe("gapped",quote(seconds=40,bid=106,ask=106.2))
        self.assertEqual(out.outcome,"COBERTURA_INSUFICIENTE")
        self.assertIsNone(out.observed_exit_price)
        self.assertIsNone(out.pnl_price_units)

    def test_no_reached_stop_or_target_keeps_position_open(self):
        book = SyntheticPaperBook()
        book.open_hypothetical(
            PaperIntent("ongoing","GOLD","buy",stop=99,target=102),quote()
        )
        out=book.observe("ongoing",quote(seconds=1,bid=100.5,ask=100.7))
        self.assertIsInstance(out,PaperPosition)
        self.assertEqual(out.last_seen,T+timedelta(seconds=1))

    def test_same_signal_id_must_not_open_twice(self):
        book=SyntheticPaperBook()
        p=PaperIntent("once","GOLD","buy",stop=99,target=102)
        book.open_hypothetical(p,quote())
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            book.open_hypothetical(p,quote(seconds=1))

    def test_closed_signal_cannot_be_opened_again(self):
        book=SyntheticPaperBook()
        p=PaperIntent("once","GOLD","buy",stop=99,target=102)
        book.open_hypothetical(p,quote())
        closed=book.observe("once",quote(seconds=1,bid=102.1,ask=102.4))
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            book.open_hypothetical(p,quote(seconds=2))
        self.assertEqual(book.observe("once",quote(seconds=2)),closed)

    def test_wrong_symbol_and_non_chronological_ticks_rejected(self):
        book=SyntheticPaperBook()
        p=PaperIntent("abc","GOLD","buy",stop=99,target=102)
        with self.assertRaisesRegex(ValueError,"Wrong asset"):
            book.open_hypothetical(p,quote(symbol="US100Cash"))
        book.open_hypothetical(p,quote())
        with self.assertRaisesRegex(ValueError,"Wrong asset"):
            book.observe("abc",quote(seconds=1,symbol="US100Cash"))
        with self.assertRaisesRegex(ValueError,"Non-chronological"):
            book.observe("abc",quote(seconds=0))

    def test_invalid_entry_stop_target_or_quote_rejected(self):
        book=SyntheticPaperBook()
        for intent in (
            PaperIntent("bad1","GOLD","buy",stop=101,target=102),
            PaperIntent("bad2","GOLD","sell",stop=100,target=95),
        ):
            with self.assertRaisesRegex(ValueError,"Stop / target"):
                book.open_hypothetical(intent,quote())
        with self.assertRaises(ValueError):
            PaperQuote("GOLD",T,bid=101,ask=100)
        with self.assertRaises(ValueError):
            PaperQuote("GOLD",datetime(2026,1,1),bid=100,ask=101)
        with self.assertRaises(ValueError):
            PaperIntent("","GOLD","buy",stop=99,target=102)
        with self.assertRaises(ValueError):
            PaperIntent("bad","GOLD","hold",stop=99,target=102)
        with self.assertRaises(ValueError):
            SyntheticPaperBook(max_quote_gap_seconds=0)

    def test_module_has_no_broker_api_and_cli_is_synthetic(self):
        book=SyntheticPaperBook()
        self.assertFalse(hasattr(book,"send_order"))
        self.assertFalse(hasattr(book,"order_send"))
        sample=synthetic_demo()
        self.assertIn("FICTICIA",sample)
        self.assertIn("Zero ordens enviadas",sample)
        r=subprocess.run([sys.executable,"-m","smc_agent.paper_execution"],
                         text=True,capture_output=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("NAO ACESSA MT5",r.stdout)


if __name__ == "__main__":
    unittest.main()
