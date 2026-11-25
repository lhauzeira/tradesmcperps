import unittest
from decimal import Decimal
from dataclasses import replace

from smc_agent.paper import PaperResult
from smc_agent.paper_report import summarize_paper_results


def modeled(event_id, status, gross, fees):
    g, f = Decimal(gross), Decimal(fees)
    return PaperResult(
        event_id, status, 2,
        paper_entry_price=Decimal("4000.20"),
        paper_exit_price=Decimal("4001.90"),
        paper_lots=Decimal("0.03"),
        modeled_gross_usd=g,
        modeled_net_usd=g-f,
        modeled_fees_usd=f,
    )


class BatchReportTests(unittest.TestCase):
    def test_aggregates_without_claiming_broker_win_rate(self):
        report = summarize_paper_results([
            modeled("one", "PAPER_TARGET_MODEL", "5.50", ".30"),
            modeled("two", "PAPER_STOP_MODEL", "-4.00", ".30"),
            PaperResult("three", "AMBIGUOUS_INTRA_BAR", 2,
                        paper_entry_price=Decimal("4000.20"),
                        paper_lots=Decimal("0.03")),
            PaperResult("four", "SESSION_UNVERIFIED", 0),
            PaperResult("five", "NO_TRADE_MIN_LOT_RISK", 0),
        ], dataset_label="FABRICATED_QUOTES_ONLY")
        self.assertEqual(report.scenarios_submitted, 5)
        self.assertEqual(report.modeled_target_touches, 1)
        self.assertEqual(report.modeled_stop_touches, 1)
        self.assertEqual(report.unresolved_or_blocked, 3)
        self.assertEqual(report.estimated_net_resolved_subset_only_usd,
                         Decimal("0.90"))
        self.assertIsNone(report.verified_realized_pnl_usd)
        self.assertIsNone(report.verified_win_rate)
        self.assertIsNone(report.verified_profit_factor)
        self.assertEqual(report.completed_live_orders, 0)

    def test_repeated_signals_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            summarize_paper_results([
                PaperResult("repeat", "SESSION_UNVERIFIED", 0),
                PaperResult("repeat", "NO_ENTRY_STALE_QUOTES", 0),
            ], dataset_label="synthetic")

    def test_unknown_profit_claim_status_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            summarize_paper_results([
                PaperResult("fake", "PROFIT_CONFIRMED", 2)
            ], dataset_label="test")

    def test_ambiguous_case_cannot_have_pnl(self):
        with self.assertRaisesRegex(ValueError, "Inconclusive"):
            summarize_paper_results([
                PaperResult("a", "AMBIGUOUS_INTRA_BAR", 2,
                            modeled_net_usd=Decimal("10"))
            ], dataset_label="test")

    def test_resolved_case_must_have_provenance_of_its_math(self):
        with self.assertRaisesRegex(ValueError, "missing required"):
            summarize_paper_results([
                PaperResult("x", "PAPER_TARGET_MODEL", 2)
            ], dataset_label="test")

    def test_invalid_fees_rejected(self):
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            summarize_paper_results([
                replace(modeled("x", "PAPER_STOP_MODEL", "-1", ".1"),
                        modeled_net_usd=Decimal("100"))
            ], dataset_label="test")

    def test_zero_dataset_allowed_but_no_winrate(self):
        report = summarize_paper_results([], dataset_label="NO_SIGNALS_YET")
        self.assertEqual(report.scenarios_submitted, 0)
        self.assertIsNone(report.verified_win_rate)
        self.assertEqual(report.estimated_net_resolved_subset_only_usd,
                         Decimal("0"))

    def test_dataset_label_required(self):
        with self.assertRaises(ValueError):
            summarize_paper_results([], dataset_label="   ")

    def test_nan_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            summarize_paper_results([
                replace(modeled("x", "PAPER_TARGET_MODEL", "5", ".1"),
                        modeled_gross_usd=Decimal("NaN"))
            ], dataset_label="synthetic")


if __name__ == "__main__":
    unittest.main()
