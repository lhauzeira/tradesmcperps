"""Durable, fail-closed preparation ledger for FUTURE demo-only orders.

This is NOT an order journal reporting actual broker fills. No MT5 import,
no order_send, no credentials, and no assertion about brokerage activity.
All rows are RESEARCH INTENTS and must be reconciled against the broker
by a future separately-authorized executor before any submission.

Crash/restart design: an unresolved prepared/simulated unknown intent
becomes RECONCILE_REQUIRED; repeating the same event_id does NOT create
another intent and cannot submit a second order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3


def _decimal(value, name: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{name} inválido")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} inválido") from None
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{name} inválido")
    return str(number.normalize())


def _when(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp deve ter fuso")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchOrderIntent:
    event_id: str
    venue: str
    symbol: str
    side: str
    volume: str
    stop: str
    target: str

    def __post_init__(self):
        if (not all(isinstance(v, str) and 0 < len(v.strip()) <= 120
                    for v in (self.event_id,self.venue,self.symbol))):
            raise ValueError("Identidade inválida de intenção")
        if self.venue != "XMGlobal-MT5 5 (DEMO-RESEARCH)":
            raise ValueError("Somente pesquisa XM DEMO neste diário")
        if self.side not in ("buy","sell"):
            raise ValueError("Lado inválido")
        for key in ("volume", "stop", "target"):
            _decimal(getattr(self,key),key)

    def immutable(self) -> tuple[str,...]:
        return (self.event_id,self.venue,self.symbol,self.side,
                _decimal(self.volume,"volume"),_decimal(self.stop,"stop"),
                _decimal(self.target,"target"))


STATES = frozenset((
    "PREPARED_RESEARCH", "SIMULATED_SEND_UNKNOWN",
    "RECONCILE_REQUIRED", "BLOCKED_RESEARCH", "RESOLVED_NO_ORDER"
))

_ALLOWED_TRANSITIONS = {
    "PREPARED_RESEARCH": frozenset((
        "SIMULATED_SEND_UNKNOWN", "BLOCKED_RESEARCH",
        "RESOLVED_NO_ORDER", "RECONCILE_REQUIRED"
    )),
    "SIMULATED_SEND_UNKNOWN": frozenset(("RECONCILE_REQUIRED",)),
    "RECONCILE_REQUIRED": frozenset(("RESOLVED_NO_ORDER",)),
    "BLOCKED_RESEARCH": frozenset(),
    "RESOLVED_NO_ORDER": frozenset(),
}
_UNRESOLVED = ("PREPARED_RESEARCH", "SIMULATED_SEND_UNKNOWN")


class ResearchIntentJournal:
    """SQLite lock + immutable identity. Never submits or closes positions."""

    def __init__(self, filename: str | Path):
        self.db = sqlite3.connect(str(filename), timeout=15, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS research_intents (
            event_id TEXT PRIMARY KEY,
            venue TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            volume TEXT NOT NULL,
            stop TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            created_utc TEXT NOT NULL,
            last_updated_utc TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS research_events (
            event_id TEXT NOT NULL,
            status TEXT NOT NULL,
            happened_utc TEXT NOT NULL,
            note TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES research_intents(event_id)
        )""")

    def __enter__(self):
        return self

    def __exit__(self, typ, value, traceback):
        self.close()

    def close(self):
        self.db.close()

    def register(self, intent: ResearchOrderIntent, *, at: datetime) -> bool:
        """Exactly-once reservation. Duplicate ID cannot be reprocessed."""
        created = _when(at)
        immutable = intent.immutable()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT venue,symbol,side,volume,stop,target FROM research_intents "
                "WHERE event_id=?", (intent.event_id,)
            ).fetchone()
            if row is not None:
                if tuple(row) != immutable[1:]:
                    raise ValueError("ID de intenção reutilizado com parâmetros diferentes")
                self.db.execute("COMMIT")
                return False
            self.db.execute(
                """INSERT INTO research_intents
                (event_id,venue,symbol,side,volume,stop,target,
                 status,created_utc,last_updated_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                immutable+("PREPARED_RESEARCH",created,created)
            )
            self.db.execute(
                "INSERT INTO research_events VALUES (?,?,?,?)",
                (intent.event_id,"PREPARED_RESEARCH",created,"Somente pesquisa")
            )
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def state(self, event_id: str) -> str | None:
        row=self.db.execute(
            "SELECT status FROM research_intents WHERE event_id=?",
            (event_id,)
        ).fetchone()
        return row[0] if row is not None else None

    def transition(self, event_id: str, next_state: str, *,
                   at: datetime, note: str = "") -> bool:
        """A simulated state transition, NEVER a brokerage confirmation."""
        timestamp = _when(at)
        if next_state not in STATES:
            raise ValueError("Estado não reconhecido")
        if not isinstance(note,str) or len(note)>300:
            raise ValueError("Nota inválida")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute(
                "SELECT status,last_updated_utc FROM research_intents "
                "WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise KeyError("Intenção inexistente")
            old,last_updated=row
            if old == next_state:
                self.db.execute("COMMIT")
                return False
            if next_state not in _ALLOWED_TRANSITIONS[old]:
                raise ValueError(f"Transição não permitida: {old} -> {next_state}")
            if timestamp < last_updated:
                raise ValueError("Evento retroativo não permitido")
            self.db.execute(
                "UPDATE research_intents SET status=?,last_updated_utc=? "
                "WHERE event_id=?",(next_state,timestamp,event_id)
            )
            self.db.execute(
                "INSERT INTO research_events VALUES (?,?,?,?)",
                (event_id,next_state,timestamp,note)
            )
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def quarantine_unresolved_after_restart(self, *, at: datetime) -> int:
        """Treat all outstanding intentions as uncertain after a crash.

        This does not confirm execution. Only a human/authorized future
        reconciliation can close the research-only incident.
        """
        stamp=_when(at)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            rows=self.db.execute(
                "SELECT event_id,last_updated_utc FROM research_intents "
                "WHERE status IN (?,?)",_UNRESOLVED
            ).fetchall()
            for event_id,last in rows:
                if stamp < last:
                    raise ValueError("Relógio regressivo ao reiniciar")
                self.db.execute(
                    "UPDATE research_intents SET status=?,last_updated_utc=? "
                    "WHERE event_id=?",
                    ("RECONCILE_REQUIRED",stamp,event_id)
                )
                self.db.execute(
                    "INSERT INTO research_events VALUES (?,?,?,?)",
                    (event_id,"RECONCILE_REQUIRED",stamp,
                     "Reinício: não repetir envio sem reconciliação")
                )
            self.db.execute("COMMIT")
            return len(rows)
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def counts(self) -> dict[str,int]:
        return dict(self.db.execute(
            "SELECT status,COUNT(*) FROM research_intents GROUP BY status"
        ).fetchall())
