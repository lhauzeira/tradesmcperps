import unittest

from smc_agent.lifecycle_demo import demo


class LifecycleDemoTests(unittest.TestCase):
    def test_demo_never_claims_a_fill_or_profit(self):
        result = demo()
        self.assertEqual(result["demonstration"], "synthetic_only")
        self.assertTrue(result["not_a_real_signal"])
        self.assertEqual(result["automated_orders_sent"], 0)
        self.assertEqual(result["verified_broker_fills"], 0)
        self.assertFalse(result["verified_realized_profit"])

    def test_demo_skips_earlier_candle_and_deduplicates(self):
        result = demo()
        self.assertEqual(result["observed_price_status"], "TARGET_LEVEL_TOUCHED")
        self.assertEqual(result["post_publication_closed_candles_analyzed"], 2)
        self.assertTrue(result["duplicate_record_ignored"])
        self.assertEqual(result["journal_counts"]["registered_signal"], 1)
        self.assertEqual(result["journal_counts"]["distinct_observations"], 1)


if __name__ == "__main__":
    unittest.main()
