"""Crash-conservative single-controller process lock for FUTURE XM DEMO.

This module has ZERO trading functions, MT5 imports or credentials.
A durable SQLite lease prevents a second robot process from believing
it is the only controller. Unlike a typical expiring lease, a crash
DOES NOT auto-release it: unknown brokerage state requires explicit
operator reconciliation before reuse.

The lease does not assert which MT5 account is open, nor grant orders.
A future authorized executor must use one account-specific private
database and independently check existing positions/orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
import sqlite3


def _utc(dt: datetime) -> str:
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("UTC timestamp with time zone required")
    return dt.astimezone(timezone.utc).isoformat()


class ExclusiveControllerLease:
    """SQLite single-owner claim; no time-based automatic lock stealing."""

    def __init__(self, filename: str | Path):
        self._token=token_hex(32)
        self._key=sha256(self._token.encode("ascii")).hexdigest()
        self._db=sqlite3.connect(str(filename),timeout=15,isolation_level=None)
        self._db.execute("PRAGMA busy_timeout=15000")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS exclusive_controller (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                owner_digest TEXT NOT NULL,
                acquired_at_utc TEXT NOT NULL
            )"""
        )

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        """Close without removing the persistent guard on unknown crash."""
        self._db.close()

    def held_by_this_process(self) -> bool:
        row=self._db.execute(
            "SELECT owner_digest FROM exclusive_controller WHERE singleton=1"
        ).fetchone()
        return row is not None and row[0]==self._key

    def is_locked(self) -> bool:
        return self._db.execute(
            "SELECT 1 FROM exclusive_controller WHERE singleton=1"
        ).fetchone() is not None

    def acquire(self, *, now: datetime) -> bool:
        """False means another process or unresolved previous run owns it."""
        stamp=_utc(now)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row=self._db.execute(
                "SELECT owner_digest FROM exclusive_controller WHERE singleton=1"
            ).fetchone()
            if row is not None:
                self._db.execute("COMMIT")
                return row[0]==self._key
            self._db.execute(
                "INSERT INTO exclusive_controller VALUES(1,?,?)",
                (self._key,stamp)
            )
            self._db.execute("COMMIT")
            return True
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def release_after_reconciliation(
        self, *, now: datetime, no_open_orders_or_positions_verified: bool
    ) -> None:
        """Only controlled shutdown after independent account reconciliation.

        The boolean is caller-supplied and NOT itself proof of brokerage
        state. A future executor must derive it from fresh broker results
        and still persist a corresponding audit.
        """
        _utc(now)
        if no_open_orders_or_positions_verified is not True:
            raise RuntimeError("Reconciliation required before lease release")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row=self._db.execute(
                "SELECT owner_digest FROM exclusive_controller WHERE singleton=1"
            ).fetchone()
            if row is None or row[0]!=self._key:
                raise RuntimeError("Only the current lease holder can release")
            self._db.execute(
                "DELETE FROM exclusive_controller WHERE singleton=1"
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
