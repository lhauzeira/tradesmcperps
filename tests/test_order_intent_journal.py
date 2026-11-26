"""Crash-safe fictitious research intent journal, NO brokerage execution."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from smc_agent.order_intent_journal import ResearchOrderIntent, ResearchIntentJournal

NOW=datetime(2026,11,26,18,0,tzinfo=timezone.utc)
LATER=NOW+timedelta(seconds=2)


def intent(**changes):
    fields=dict(
        event_id="synthetic-001",
        venue="XMGlobal-MT5 5 (DEMO-RESEARCH)",
        symbol="GOLD",side="buy",volume="0.01",
        stop="99.00",target="102.00",
    )
    fields.update(changes)
    return ResearchOrderIntent(**fields)


class DurableIntentJournalTests(unittest.TestCase):
    def test_reserved_once_with_same_immutable_identity(self):
        with ResearchIntentJournal(":memory:") as db:
            self.assertTrue(db.register(intent(),at=NOW))
            self.assertFalse(db.register(intent(),at=NOW))
            self.assertEqual(db.state("synthetic-001"),"PREPARED_RESEARCH")
            self.assertEqual(db.counts(),{"PREPARED_RESEARCH":1})

    def test_duplicate_id_with_different_volume_is_rejected(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(),at=NOW)
            with self.assertRaisesRegex(ValueError,"parâmetros diferentes"):
                db.register(intent(volume="0.02"),at=LATER)
            self.assertEqual(db.counts(),{"PREPARED_RESEARCH":1})

    def test_equivalent_decimal_spellings_do_not_create_new_intent(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(volume="0.010",stop="99.0"),at=NOW)
            self.assertFalse(db.register(
                intent(volume="0.01",stop="99.000"),at=LATER
            ))
            self.assertEqual(db.counts(),{"PREPARED_RESEARCH":1})

    def test_crash_restart_quarantines_pending_intent_without_resending(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path=Path(folder)/"intents.sqlite3"
            with ResearchIntentJournal(db_path) as db:
                db.register(intent(),at=NOW)
            with ResearchIntentJournal(db_path) as restarted:
                self.assertEqual(
                    restarted.quarantine_unresolved_after_restart(at=LATER),1
                )
                self.assertEqual(restarted.state("synthetic-001"),
                                 "RECONCILE_REQUIRED")
                self.assertFalse(restarted.register(intent(),at=LATER))
                with self.assertRaises(ValueError):
                    restarted.transition(
                        "synthetic-001","PREPARED_RESEARCH",at=LATER
                    )
            with ResearchIntentJournal(db_path) as again:
                self.assertEqual(
                    again.quarantine_unresolved_after_restart(at=LATER),0
                )
                self.assertEqual(again.counts(),{"RECONCILE_REQUIRED":1})

    def test_restart_blocks_new_signal_until_quarantine_and_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"intents.sqlite3"
            with ResearchIntentJournal(path) as first:
                first.register(intent(),at=NOW)
                first.transition(
                    "synthetic-001","PAPER_POSITION_OPEN",
                    at=NOW+timedelta(seconds=1)
                )
            with ResearchIntentJournal(path) as restarted:
                fresh=intent(event_id="synthetic-NEW")
                with self.assertRaisesRegex(RuntimeError,"reconciliação"):
                    restarted.register(fresh,at=LATER)
                self.assertEqual(restarted.quarantine_unresolved_after_restart(
                    at=LATER
                ),1)
                self.assertEqual(restarted.pending_reconciliation_count(),1)
                with self.assertRaisesRegex(RuntimeError,"reconciliação"):
                    restarted.register(fresh,at=LATER+timedelta(seconds=1))
                # Resolving in the research journal does NOT confirm a fill.
                restarted.transition(
                    "synthetic-001","RESOLVED_NO_ORDER",
                    at=LATER+timedelta(seconds=1)
                )
                self.assertEqual(restarted.pending_reconciliation_count(),0)
                self.assertTrue(restarted.register(
                    fresh,at=LATER+timedelta(seconds=2)
                ))

    def test_terminal_research_outcome_does_not_block_next_session(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"intents.sqlite3"
            with ResearchIntentJournal(path) as first:
                first.register(intent(),at=NOW)
                first.transition(
                    "synthetic-001","PAPER_POSITION_OPEN",
                    at=NOW+timedelta(seconds=1)
                )
                first.transition(
                    "synthetic-001","SIMULATED_TARGET_OBSERVED",
                    at=LATER
                )
            with ResearchIntentJournal(path) as restarted:
                self.assertEqual(restarted.pending_reconciliation_count(),0)
                self.assertTrue(restarted.register(
                    intent(event_id="synthetic-NEXT"),
                    at=LATER+timedelta(seconds=1)
                ))

    def test_unknown_simulated_transmission_is_always_quarantined(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(),at=NOW)
            db.transition("synthetic-001","SIMULATED_SEND_UNKNOWN",at=LATER)
            self.assertEqual(
                db.quarantine_unresolved_after_restart(
                    at=LATER+timedelta(seconds=1)
                ),1
            )
            self.assertEqual(db.state("synthetic-001"),"RECONCILE_REQUIRED")

    def test_resolved_research_intent_cannot_reenter_pipeline(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(),at=NOW)
            db.transition("synthetic-001","RESOLVED_NO_ORDER",at=LATER)
            self.assertFalse(db.register(intent(),at=LATER))
            with self.assertRaises(ValueError):
                db.transition(
                    "synthetic-001","PREPARED_RESEARCH",
                    at=LATER+timedelta(seconds=1)
                )
            self.assertEqual(
                db.quarantine_unresolved_after_restart(
                    at=LATER+timedelta(seconds=1)
                ),0
            )

    def test_blocked_research_is_terminal(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(),at=NOW)
            db.transition("synthetic-001","BLOCKED_RESEARCH",at=LATER)
            with self.assertRaises(ValueError):
                db.transition(
                    "synthetic-001","SIMULATED_SEND_UNKNOWN",
                    at=LATER+timedelta(seconds=1)
                )

    def test_reconciliation_resolved_only_as_no_order_in_research(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(),at=NOW)
            db.quarantine_unresolved_after_restart(at=LATER)
            self.assertTrue(db.transition(
                "synthetic-001","RESOLVED_NO_ORDER",
                at=LATER+timedelta(seconds=1)
            ))
            self.assertEqual(db.counts(),{"RESOLVED_NO_ORDER":1})

    def test_bad_state_and_unknown_id_are_not_silently_accepted(self):
        with ResearchIntentJournal(":memory:") as db:
            with self.assertRaises(ValueError):
                db.transition("missing","ORDER_EXECUTED",at=NOW)
            with self.assertRaises(KeyError):
                db.transition("missing","BLOCKED_RESEARCH",at=NOW)

    def test_retroactive_reconciliation_rejected(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(),at=LATER)
            with self.assertRaises(ValueError):
                db.quarantine_unresolved_after_restart(at=NOW)
            self.assertEqual(db.counts(),{"PREPARED_RESEARCH":1})

    def test_bad_identity_rejected(self):
        for kwargs in (
            dict(event_id=""),
            dict(venue="XM-REAL"),
            dict(side="hold"),
            dict(volume="-1"),
            dict(stop="NaN"),
            dict(target="0"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    intent(**kwargs)

    def test_no_brokerage_order_api_is_exposed(self):
        with ResearchIntentJournal(":memory:") as db:
            self.assertFalse(hasattr(db,"order_send"))
            self.assertFalse(hasattr(db,"send_order"))
            db.register(intent(),at=NOW)
            with self.assertRaises(ValueError):
                db.transition(
                    "synthetic-001","BROKER_CONFIRMED",at=LATER
                )

    def test_transactions_persist_audit_log_and_not_account_secrets(self):
        with ResearchIntentJournal(":memory:") as db:
            db.register(intent(),at=NOW)
            db.transition("synthetic-001","BLOCKED_RESEARCH",at=LATER,
                          note="Símbolo fechado no feriado")
            rows=db.db.execute(
                "SELECT status FROM research_events ORDER BY rowid"
            ).fetchall()
            self.assertEqual(rows,[
                ("PREPARED_RESEARCH",),("BLOCKED_RESEARCH",)
            ])
            names={r[1] for r in db.db.execute("PRAGMA table_info(research_intents)")}
            self.assertNotIn("login",names)
            self.assertNotIn("password",names)
            self.assertNotIn("token",names)

if __name__=="__main__":
    unittest.main()
