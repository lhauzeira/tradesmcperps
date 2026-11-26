"""Durable exclusive-controller simulation, no broker SDK or transactions."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from smc_agent.execution_lease import ExclusiveControllerLease

T=datetime(2026,11,26,20,0,tzinfo=timezone.utc)


class ExclusiveControllerLeaseTests(unittest.TestCase):
    def test_first_controller_wins_and_second_cannot_claim(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"controller.sqlite3"
            with ExclusiveControllerLease(path) as first, ExclusiveControllerLease(path) as second:
                self.assertTrue(first.acquire(now=T))
                self.assertTrue(first.held_by_this_process())
                self.assertTrue(second.is_locked())
                self.assertFalse(second.acquire(now=T))
                self.assertFalse(second.held_by_this_process())
                self.assertTrue(first.acquire(now=T))

    def test_clean_reconciled_release_allows_new_controller(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"controller.sqlite3"
            with ExclusiveControllerLease(path) as first:
                first.acquire(now=T)
                first.release_after_reconciliation(
                    now=T,no_open_orders_or_positions_verified=True
                )
                self.assertFalse(first.is_locked())
            with ExclusiveControllerLease(path) as second:
                self.assertTrue(second.acquire(now=T))
                self.assertTrue(second.held_by_this_process())

    def test_shutdown_without_verified_reconciliation_cannot_clear_lease(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"controller.sqlite3"
            with ExclusiveControllerLease(path) as first:
                first.acquire(now=T)
                with self.assertRaisesRegex(RuntimeError,"Reconciliation"):
                    first.release_after_reconciliation(
                        now=T,no_open_orders_or_positions_verified=False
                    )
                self.assertTrue(first.is_locked())

    def test_crash_close_does_not_auto_expire_or_steal_lease(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"controller.sqlite3"
            first=ExclusiveControllerLease(path)
            first.acquire(now=T)
            first.close()  # Pretend the first process crashed
            with ExclusiveControllerLease(path) as restarted:
                self.assertTrue(restarted.is_locked())
                self.assertFalse(restarted.acquire(now=T))
                self.assertFalse(restarted.acquire(
                    now=datetime(2036,1,1,tzinfo=timezone.utc)
                ))
                with self.assertRaisesRegex(RuntimeError,"holder"):
                    restarted.release_after_reconciliation(
                        now=T,no_open_orders_or_positions_verified=True
                    )

    def test_same_process_reacquire_is_idempotent(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"controller.sqlite3"
            with ExclusiveControllerLease(path) as lease:
                self.assertTrue(lease.acquire(now=T))
                self.assertTrue(lease.acquire(now=T))
                records=lease._db.execute(
                    "SELECT COUNT(*) FROM exclusive_controller"
                ).fetchone()[0]
                self.assertEqual(records,1)

    def test_naive_timestamp_and_non_boolean_verification_rejected(self):
        with ExclusiveControllerLease(":memory:") as lease:
            with self.assertRaises(ValueError):
                lease.acquire(now=datetime(2026,11,26))
            lease.acquire(now=T)
            with self.assertRaises(RuntimeError):
                lease.release_after_reconciliation(
                    now=T,no_open_orders_or_positions_verified=1
                )
            self.assertTrue(lease.is_locked())

    def test_hash_only_stored_no_account_identity_or_token(self):
        with ExclusiveControllerLease(":memory:") as lease:
            lease.acquire(now=T)
            names={row[1] for row in lease._db.execute(
                "PRAGMA table_info(exclusive_controller)"
            )}
            self.assertEqual(names,{"singleton","owner_digest","acquired_at_utc"})
            row=lease._db.execute(
                "SELECT owner_digest FROM exclusive_controller"
            ).fetchone()
            self.assertEqual(len(row[0]),64)
            self.assertNotIn(lease._token,row[0])

    def test_no_mt5_api_or_order_methods_in_controller(self):
        with ExclusiveControllerLease(":memory:") as lease:
            self.assertFalse(hasattr(lease,"order_send"))
            self.assertFalse(hasattr(lease,"send_order"))
            self.assertFalse(hasattr(lease,"close_position"))


if __name__=="__main__":
    unittest.main()
