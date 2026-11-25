"""Offline XM GOLD position-sizing tests — no account connection or orders."""
from dataclasses import replace
from decimal import Decimal
import unittest

from smc_agent.xm_gold_risk import (
    XM_GOLD_DEMO_SNAPSHOT, GoldContractSnapshot, size_under_risk_budget,
    theoretical_stop_loss_usd, risk_example,
)


class XMGoldRiskTests(unittest.TestCase):
    def test_reference_contract_from_mt5_user_screenshot(self):
        spec = XM_GOLD_DEMO_SNAPSHOT
        self.assertEqual(spec.symbol, "GOLD")
        self.assertEqual(spec.venue, "XMGlobal-MT5 5 (demo)")
        self.assertEqual(spec.lot_min, Decimal("0.01"))
        self.assertEqual(spec.lot_step, Decimal("0.001"))
        self.assertEqual(spec.lot_max, Decimal("50"))
        self.assertEqual(spec.tick_size, Decimal("0.01"))
        self.assertEqual(spec.tick_value_usd_per_lot, Decimal("1"))
        self.assertEqual(spec.contract_size, Decimal("100"))
        self.assertEqual(spec.swap_long_points, Decimal("-69.5"))
        self.assertEqual(spec.swap_short_points, Decimal("15.07"))
        self.assertEqual(spec.wednesday_swap_multiplier, 3)

    def test_dollar_risk_of_one_dollar_gold_move(self):
        for lots, dollars in (("0.01","1"), ("0.10","10"), ("1","100")):
            loss = theoretical_stop_loss_usd(
                side="buy", entry="4000.00", stop="3999.00",
                volume_lots=lots)
            self.assertEqual(loss, Decimal(dollars))

    def test_sizing_observes_min_and_increment(self):
        r = size_under_risk_budget(
            side="buy", entry="4000", stop="3999",
            risk_budget_usd="2.20", extra_cost_reserve_usd="1.00")
        self.assertEqual(r.status, "RESEARCH_SIZE_ONLY")
        self.assertEqual(r.volume_lots, Decimal("0.012"))
        self.assertEqual(r.theoretical_stop_loss_usd, Decimal("1.200"))
        self.assertEqual(r.total_budgeted_loss_usd, Decimal("2.200"))
        self.assertLessEqual(r.total_budgeted_loss_usd, r.risk_budget_usd)

    def test_caps_at_maximum_volume(self):
        r = size_under_risk_budget(
            side="sell", entry="4000", stop="4000.01",
            risk_budget_usd="100000", extra_cost_reserve_usd="0")
        self.assertEqual(r.volume_lots, Decimal("50"))

    def test_refuses_trade_below_min_lot_budget(self):
        r = size_under_risk_budget(
            side="buy", entry="4000", stop="3990",
            risk_budget_usd="5", extra_cost_reserve_usd="1")
        self.assertEqual(r.status, "NO_TRADE")
        self.assertIsNone(r.volume_lots)

    def test_budget_not_enough_for_reserve(self):
        r = size_under_risk_budget(
            side="buy", entry="4000", stop="3999",
            risk_budget_usd="1", extra_cost_reserve_usd="1")
        self.assertEqual(r.status, "NO_TRADE")

    def test_buy_stop_must_be_below_entry(self):
        with self.assertRaisesRegex(ValueError, "Long stop"):
            size_under_risk_budget(
                side="buy", entry="4000", stop="4001",
                risk_budget_usd="10", extra_cost_reserve_usd="1")

    def test_sell_stop_must_be_above_entry(self):
        with self.assertRaisesRegex(ValueError, "Short stop"):
            size_under_risk_budget(
                side="sell", entry="4000", stop="3999",
                risk_budget_usd="10", extra_cost_reserve_usd="1")

    def test_rejects_bad_side(self):
        with self.assertRaisesRegex(ValueError, "Side"):
            size_under_risk_budget(
                side="hold", entry="4000", stop="3999",
                risk_budget_usd="10", extra_cost_reserve_usd="1")

    def test_rejects_off_tick_price(self):
        with self.assertRaisesRegex(ValueError, "tick size"):
            size_under_risk_budget(
                side="buy", entry="4000.001", stop="3999",
                risk_budget_usd="10", extra_cost_reserve_usd="1")

    def test_rejects_nan_and_infinite(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaisesRegex(ValueError, "finite"):
                size_under_risk_budget(
                    side="buy", entry="4000", stop="3999",
                    risk_budget_usd=value, extra_cost_reserve_usd="1")

    def test_rejects_negative_cost(self):
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            size_under_risk_budget(
                side="buy", entry="4000", stop="3999",
                risk_budget_usd="10", extra_cost_reserve_usd="-1")

    def test_rejects_zero_risk_budget(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            size_under_risk_budget(
                side="buy", entry="4000", stop="3999",
                risk_budget_usd="0", extra_cost_reserve_usd="0")

    def test_rejects_wrong_lot_step(self):
        with self.assertRaisesRegex(ValueError, "step"):
            XM_GOLD_DEMO_SNAPSHOT.valid_volume("0.0105")

    def test_accepts_lot_with_three_decimal_places(self):
        self.assertEqual(XM_GOLD_DEMO_SNAPSHOT.valid_volume("0.011"),
                         Decimal("0.011"))

    def test_refuses_below_min_and_above_max(self):
        for volume in ("0.009", "50.001", "-2", "0"):
            with self.assertRaisesRegex(ValueError, "range"):
                XM_GOLD_DEMO_SNAPSHOT.valid_volume(volume)

    def test_bad_symbol_contract_rejected(self):
        with self.assertRaises(ValueError):
            replace(XM_GOLD_DEMO_SNAPSHOT, tick_size=Decimal("0"))
        with self.assertRaises(ValueError):
            replace(XM_GOLD_DEMO_SNAPSHOT, lot_min=Decimal("51"))

    def test_without_explicit_reserve_typeerror(self):
        with self.assertRaises(TypeError):
            size_under_risk_budget(
                side="buy", entry="4000", stop="3999",
                risk_budget_usd="10")

    def test_demo_never_claims_real_orders(self):
        output = risk_example()
        self.assertEqual(output["orders_sent"], "0")
        self.assertFalse(output["actual_broker_fill_verified"])
        self.assertIn("SYNTHETIC_", output["dataset"])


if __name__ == "__main__":
    unittest.main()
