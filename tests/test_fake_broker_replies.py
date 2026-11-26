"""Mock-only order response paths never authorize actual orders or retries."""
from dataclasses import replace
from decimal import Decimal
import unittest

from smc_agent.fake_broker_replies import (
    FakeBrokerReply, classify_fake_broker_reply
)

D=Decimal


def reply(**changes):
    data=dict(
        signal_id="research-001",symbol="GOLD",requested_lots=D("0.10"),
        status="FAKE_FILLED",acknowledged_lots=D("0.10"),
        synthetic_ticket="FAKE-1234"
    )
    data.update(changes)
    return FakeBrokerReply(**data)


def evaluate(r):
    return classify_fake_broker_reply(
        r,expected_symbol="GOLD",expected_signal_id="research-001"
    )


class FakeOrderResponseTests(unittest.TestCase):
    def test_hypothetical_fill_never_counts_as_real_position(self):
        out=evaluate(reply())
        self.assertEqual(out.state,"PREENCHIDA_FICTICIAMENTE_EXIGE_CONFERENCIA")
        self.assertTrue(out.requires_position_reconciliation)
        self.assertFalse(out.can_submit_orders)
        self.assertFalse(out.automatic_retry_allowed)

    def test_partial_fill_requires_reconciliation(self):
        out=evaluate(reply(status="FAKE_PARTIAL",acknowledged_lots=D("0.04")))
        self.assertEqual(out.state,"PARCIAL_FICTICIA_EXIGE_CONFERENCIA")
        self.assertTrue(out.requires_position_reconciliation)
        self.assertFalse(out.automatic_retry_allowed)

    def test_rejected_order_may_not_be_resubmitted_automatically(self):
        out=evaluate(reply(status="FAKE_REJECTED",acknowledged_lots=D("0")))
        self.assertEqual(out.state,"REJEICAO_FICTICIA")
        self.assertFalse(out.automatic_retry_allowed)

    def test_timeout_always_quarantines_even_with_filled_lots_hint(self):
        for v in (None,D("0"),D("0.10")):
            with self.subTest(volume=v):
                out=evaluate(reply(status="FAKE_TIMEOUT",
                                   acknowledged_lots=v))
                self.assertEqual(out.state,"QUARENTENA")
                self.assertFalse(out.automatic_retry_allowed)

    def test_response_with_wrong_symbol_or_id_quarantines(self):
        for values in (dict(symbol="US100Cash"),
                       dict(signal_id="different")):
            out=evaluate(reply(**values))
            self.assertEqual(out.state,"QUARENTENA")
            self.assertTrue(out.requires_position_reconciliation)

    def test_conflicting_reject_with_positive_fill_quarantines(self):
        out=evaluate(reply(status="FAKE_REJECTED",
                           acknowledged_lots=D("0.01")))
        self.assertEqual(out.state,"QUARENTENA")

    def test_missing_ticket_or_confirmed_volume_quarantines(self):
        for values in (dict(synthetic_ticket=None),
                       dict(acknowledged_lots=None),
                       dict(acknowledged_lots=D("0.05"))):
            with self.subTest(values=values):
                self.assertEqual(evaluate(reply(**values)).state,"QUARENTENA")

    def test_partial_zero_or_full_volume_is_inconsistent(self):
        for v in (D("0"),D("0.10"),None):
            out=evaluate(reply(status="FAKE_PARTIAL",acknowledged_lots=v))
            self.assertEqual(out.state,"QUARENTENA")

    def test_overfill_is_not_accepted(self):
        out=evaluate(reply(acknowledged_lots=D("0.11")))
        self.assertEqual(out.state,"QUARENTENA")

    def test_unknown_response_always_requires_reconciliation(self):
        out=evaluate(reply(status="FAKE_UNKNOWN"))
        self.assertEqual(out.state,"QUARENTENA")
        self.assertTrue(out.requires_position_reconciliation)

    def test_cannot_forge_permission_to_retry_or_execute(self):
        out=evaluate(reply())
        with self.assertRaisesRegex(ValueError,"cannot authorize"):
            replace(out,can_submit_orders=True)
        with self.assertRaisesRegex(ValueError,"cannot authorize"):
            replace(out,automatic_retry_allowed=True)

    def test_invalid_or_nan_volume_rejected(self):
        with self.assertRaises(ValueError):
            reply(requested_lots=D("0"))
        with self.assertRaises(ValueError):
            reply(acknowledged_lots=D("NaN"))
        with self.assertRaises(ValueError):
            reply(status="REAL_FILLED")


if __name__=="__main__":
    unittest.main()
