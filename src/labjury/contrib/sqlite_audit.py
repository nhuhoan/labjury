"""SQLite-backed :class:`~labjury.plugins.AuditLog` reference backend.

Durable and dependency-free: the stdlib :mod:`sqlite3` module, wrapped in
:func:`asyncio.to_thread` so blocking calls never stall the event loop. The
backend owns a file path (not an injected connection) because a ``sqlite3``
connection carries thread affinity and each operation runs on an arbitrary
thread-pool thread — so each op opens its own short-lived connection, and
SQLite's own file locking serializes concurrent access.

Events are stored as ``json.dumps(event.to_dict())`` and read back through
:meth:`AuditEvent.from_dict` — the backend touches only the serialization seam,
never LabJury's internal types. Append-only by contract: ``record`` and reads
only, no update or delete.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

from labjury.audit import AuditEvent


class SqliteAuditLog:
    def __init__(self, path: str, table: str = "labjury_audit") -> None:
        self._path = path
        self._table = table
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event_id TEXT NOT NULL, "
                "correlation_id TEXT NOT NULL, "
                "payload TEXT NOT NULL)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {table}_corr "
                f"ON {table}(correlation_id)"
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=30)

    async def record(self, event: AuditEvent) -> None:
        payload = json.dumps(event.to_dict())

        def _write() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    f"INSERT INTO {self._table} "
                    "(event_id, correlation_id, payload) VALUES (?, ?, ?)",
                    (event.event_id, event.correlation_id, payload),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_write)

    async def by_correlation(self, correlation_id: str) -> list[AuditEvent]:
        def _read() -> list[AuditEvent]:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT payload FROM {self._table} "
                    "WHERE correlation_id = ? ORDER BY seq",
                    (correlation_id,),
                ).fetchall()
            finally:
                conn.close()
            return [AuditEvent.from_dict(json.loads(p)) for (p,) in rows]

        return await asyncio.to_thread(_read)
