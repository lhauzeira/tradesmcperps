import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import unittest

from smc_agent.lifecycle import PublishedSignal, Observation
from smc_agent.journal import SignalJournal

UTC = timezone.utc
CREATED = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)


def plan(signal_id="audit-1", entry=100.):
    return PublishedSignal(signal_id=signal_id, venue="XM-MT5",
                           symbol="XAUUSD", published_at=CREATED,
                           side="buy", entry=entry, stop=95., target=110.)


class JournalTests(unittest.TestCase):
    def test_persists_dedupe_across_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "research.sqlite3"
            event = Observation("audit-1", "AWAITING_ENTRY_LEVEL", 3)
            with SignalJournal(p) as journal:
                self.assertTrue(journal.register(plan()))
                self.assertFalse(journal.register(plan()))
                self.assertTrue(journal.append(event, as_of=CREATED+timedelta(hours=1)))
                self.assertFalse(journal.append(event, as_of=CREATED+timedelta(hours=1)))
                self.assertEqual(journal.counts("audit-1")["distinct_observations"], 1)
            with SignalJournal(p) as restarted:
                self.assertFalse(restarted.register(plan()))
                self.assertFalse(restarted.append(event, as_of=CREATED+timedelta(hours=2)))
                self.assertEqual(restarted.counts("audit-1"),
                                 {"registered_signal": 1, "distinct_observations": 1})

    def test_stores_new_progress_for_same_signal(self):
        with SignalJournal(":memory:") as db:
            db.register(plan())
            self.assertTrue(db.append(Observation("audit-1", "AWAITING_ENTRY_LEVEL", 1),
                                      as_of=CREATED+timedelta(minutes=5)))
            self.assertTrue(db.append(Observation("audit-1", "AWAITING_ENTRY_LEVEL", 2),
                                      as_of=CREATED+timedelta(minutes=10)))
            self.assertEqual(db.counts("audit-1")["distinct_observations"], 2)

    def test_collision_rejected(self):
        with SignalJournal(":memory:") as db:
            db.register(plan())
            with self.assertRaises(ValueError):
                db.register(plan(entry=101.))

    def test_unregistered_rejected(self):
        with SignalJournal(":memory:") as db:
            with self.assertRaises(ValueError):
                db.append(Observation("missing", "NO_POST_PUBLICATION_DATA", 0),
                          as_of=CREATED+timedelta(minutes=5))

    def test_before_publication_rejected(self):
        with SignalJournal(":memory:") as db:
            db.register(plan())
            with self.assertRaises(ValueError):
                db.append(Observation("audit-1", "NO_POST_PUBLICATION_DATA", 0),
                          as_of=CREATED-timedelta(seconds=1))

    def test_unknown_status_rejected(self):
        with SignalJournal(":memory:") as db:
            db.register(plan())
            with self.assertRaises(ValueError):
                db.append(Observation("audit-1", "PROFIT_CONFIRMED", 1),
                          as_of=CREATED+timedelta(minutes=5))


if __name__ == "__main__":
    unittest.main()
