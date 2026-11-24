"""Crash-resilient SQLite journal for *research observations only*.

No trade execution, API/network request, secrets, or automated sending.
The schema stores neutral signal metadata and audit states, not Telegram chats.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3

from .lifecycle import PublishedSignal, Observation, _aware

_ALLOWED_STATUSES = frozenset({
    "NO_POST_PUBLICATION_DATA", "AWAITING_ENTRY_LEVEL",
    "ENTRY_LEVEL_TOUCHED_AWAITING_OUTCOME", "TARGET_LEVEL_TOUCHED",
    "STOP_LEVEL_TOUCHED", "AMBIGUOUS_ENTRY_BAR", "AMBIGUOUS_EXIT_BAR",
    "GAP_EXIT_UNPRICED", "EXPIRED_NO_ENTRY", "UNRESOLVED_AFTER_ENTRY",
})


def _utc(moment: datetime) -> str:
    _aware(moment, "timestamp")
    return moment.astimezone(timezone.utc).isoformat()


class SignalJournal:
    """Idempotent signals and observations across Python process restarts.

    Use a writable SQLite path; never put live journal databases in GitHub.
    """

    def __init__(self, path: str | Path):
        self._connection = sqlite3.connect(str(path), timeout=10)
        self._connection.execute("PRAGMA foreign_keys=ON")
        with self._connection:
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    target REAL NOT NULL
                )""")
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS observations (
                    signal_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    observed_as_of TEXT NOT NULL,
                    status TEXT NOT NULL,
                    bars_examined INTEGER NOT NULL,
                    entry_touch_at TEXT,
                    boundary_touch_at TEXT,
                    PRIMARY KEY (signal_id, observation_id),
                    FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
                )""")

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def register(self, signal: PublishedSignal) -> bool:
        """Return True for first insert; false for identical duplicate.

        A reused identifier with different prices or dates is an error.
        """
        values = (
            signal.signal_id, signal.venue, signal.symbol, signal.side,
            _utc(signal.published_at), signal.entry, signal.stop, signal.target,
        )
        with self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values
            )
            if cursor.rowcount == 1:
                return True
            current = self._connection.execute(
                "SELECT signal_id, venue, symbol, side, published_at, entry, stop, target "
                "FROM signals WHERE signal_id=?", (signal.signal_id,)
            ).fetchone()
            if tuple(current) != values:
                raise ValueError("Signal ID reused with different immutable parameters")
        return False

    def append(self, observation: Observation, *, as_of: datetime) -> bool:
        """Append a stable observation; never record this as a verified trade."""
        cutoff = _utc(as_of)
        if observation.status not in _ALLOWED_STATUSES:
            raise ValueError("Only research observation states may be journaled")
        if observation.bars_examined < 0:
            raise ValueError("Negative bar count")
        published = self._connection.execute(
            "SELECT published_at FROM signals WHERE signal_id=?",
            (observation.signal_id,)
        ).fetchone()
        if published is None:
            raise ValueError("Register signal before appending observation")
        if cutoff < published[0]:
            # Both timestamps are canonical ISO UTC; lexical ordering is safe.
            raise ValueError("Observation predates publication")
        entry_at = _utc(observation.entry_touch_at) if observation.entry_touch_at else None
        boundary_at = _utc(observation.boundary_touch_at) if observation.boundary_touch_at else None
        identity = "|".join((
            observation.signal_id, observation.status, str(observation.bars_examined),
            entry_at or "", boundary_at or ""
        ))
        observation_id = sha256(identity.encode("utf-8")).hexdigest()[:24]
        with self._connection:
            cursor = self._connection.execute(
                """INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (observation.signal_id, observation_id, cutoff, observation.status,
                 observation.bars_examined, entry_at, boundary_at)
            )
        return cursor.rowcount == 1

    def counts(self, signal_id: str) -> dict[str, int]:
        signals = self._connection.execute(
            "SELECT COUNT(*) FROM signals WHERE signal_id=?", (signal_id,)
        ).fetchone()[0]
        observations = self._connection.execute(
            "SELECT COUNT(*) FROM observations WHERE signal_id=?", (signal_id,)
        ).fetchone()[0]
        return {"registered_signal": signals, "distinct_observations": observations}
