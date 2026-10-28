from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .domain import content_hash, stable_id


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int
    idempotency_key: str | None = None
    last_error: str | None = None


class TaskQueue(Protocol):
    def enqueue(self, kind: str, payload: dict[str, Any], *, idempotency_key: str | None = None) -> QueueMessage: ...
    def lease(self) -> QueueMessage | None: ...
    def ack(self, message_id: str) -> QueueMessage: ...
    def nack(self, message_id: str, error: str, *, requeue: bool = True) -> QueueMessage: ...
    def get(self, message_id: str) -> QueueMessage: ...


def _message_id(kind: str, payload: dict[str, Any], idempotency_key: str | None) -> str:
    return stable_id("queue", kind, idempotency_key or content_hash(payload))


class InMemoryTaskQueue:
    """Thread-safe local queue for tests and single-process demonstrations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._messages: dict[str, QueueMessage] = {}
        self._ready: list[str] = []
        self._idempotency: dict[str, str] = {}

    def enqueue(self, kind: str, payload: dict[str, Any], *, idempotency_key: str | None = None) -> QueueMessage:
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency:
                return self._messages[self._idempotency[idempotency_key]]
            message = QueueMessage(_message_id(kind, payload, idempotency_key), kind, dict(payload), "queued", 0, idempotency_key)
            existing = self._messages.get(message.message_id)
            if existing is not None:
                return existing
            self._messages[message.message_id] = message
            self._ready.append(message.message_id)
            if idempotency_key:
                self._idempotency[idempotency_key] = message.message_id
            return message

    def lease(self) -> QueueMessage | None:
        with self._lock:
            while self._ready:
                message_id = self._ready.pop(0)
                current = self._messages[message_id]
                if current.status != "queued":
                    continue
                leased = QueueMessage(
                    current.message_id, current.kind, current.payload, "leased", current.attempts + 1,
                    current.idempotency_key, current.last_error,
                )
                self._messages[message_id] = leased
                return leased
            return None

    def ack(self, message_id: str) -> QueueMessage:
        with self._lock:
            current = self._messages[message_id]
            if current.status not in {"leased", "succeeded"}:
                raise ValueError(f"cannot acknowledge queue message in state {current.status}")
            updated = QueueMessage(current.message_id, current.kind, current.payload, "succeeded", current.attempts, current.idempotency_key, current.last_error)
            self._messages[message_id] = updated
            return updated

    def nack(self, message_id: str, error: str, *, requeue: bool = True) -> QueueMessage:
        with self._lock:
            current = self._messages[message_id]
            status = "queued" if requeue else "failed"
            updated = QueueMessage(current.message_id, current.kind, current.payload, status, current.attempts, current.idempotency_key, error)
            self._messages[message_id] = updated
            if requeue:
                self._ready.append(message_id)
            return updated

    def get(self, message_id: str) -> QueueMessage:
        with self._lock:
            return self._messages[message_id]


class SQLiteTaskQueue:
    """Small durable queue backed by SQLite for a local worker deployment."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS queue_messages (
                    message_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT UNIQUE,
                    last_error TEXT
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS ix_queue_messages_status ON queue_messages(status, message_id)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> QueueMessage:
        return QueueMessage(
            message_id=row["message_id"], kind=row["kind"], payload=json.loads(row["payload_json"]),
            status=row["status"], attempts=row["attempts"], idempotency_key=row["idempotency_key"],
            last_error=row["last_error"],
        )

    def enqueue(self, kind: str, payload: dict[str, Any], *, idempotency_key: str | None = None) -> QueueMessage:
        message_id = _message_id(kind, payload, idempotency_key)
        with self._connect() as connection:
            if idempotency_key:
                row = connection.execute("SELECT * FROM queue_messages WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if row:
                    return self._from_row(row)
            row = connection.execute("SELECT * FROM queue_messages WHERE message_id = ?", (message_id,)).fetchone()
            if row:
                return self._from_row(row)
            connection.execute(
                "INSERT INTO queue_messages(message_id, kind, payload_json, status, attempts, idempotency_key, last_error) VALUES (?, ?, ?, 'queued', 0, ?, NULL)",
                (message_id, kind, json.dumps(payload, ensure_ascii=False, sort_keys=True), idempotency_key),
            )
            return self.get(message_id)

    def lease(self) -> QueueMessage | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM queue_messages WHERE status = 'queued' ORDER BY message_id LIMIT 1").fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute("UPDATE queue_messages SET status = 'leased', attempts = attempts + 1 WHERE message_id = ?", (row["message_id"],))
            updated = connection.execute("SELECT * FROM queue_messages WHERE message_id = ?", (row["message_id"],)).fetchone()
            connection.commit()
            return self._from_row(updated)

    def ack(self, message_id: str) -> QueueMessage:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM queue_messages WHERE message_id = ?", (message_id,)).fetchone()
            if row is None:
                raise KeyError(message_id)
            if row["status"] not in {"leased", "succeeded"}:
                raise ValueError(f"cannot acknowledge queue message in state {row['status']}")
            connection.execute("UPDATE queue_messages SET status = 'succeeded' WHERE message_id = ?", (message_id,))
        return self.get(message_id)

    def nack(self, message_id: str, error: str, *, requeue: bool = True) -> QueueMessage:
        status = "queued" if requeue else "failed"
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM queue_messages WHERE message_id = ?", (message_id,)).fetchone() is None:
                raise KeyError(message_id)
            connection.execute("UPDATE queue_messages SET status = ?, last_error = ? WHERE message_id = ?", (status, error, message_id))
        return self.get(message_id)

    def get(self, message_id: str) -> QueueMessage:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM queue_messages WHERE message_id = ?", (message_id,)).fetchone()
            if row is None:
                raise KeyError(message_id)
            return self._from_row(row)


class LocalWorker:
    """Executes deferred Runtime runs from either local queue implementation."""

    def __init__(self, runtime: Any, queue: TaskQueue) -> None:
        self.runtime = runtime
        self.queue = queue

    def enqueue_run(self, run_id: str, *, idempotency_key: str | None = None) -> QueueMessage:
        return self.queue.enqueue("run.execute", {"run_id": run_id}, idempotency_key=idempotency_key or run_id)

    def run_once(self) -> Any | None:
        message = self.queue.lease()
        if message is None:
            return None
        if message.kind != "run.execute" or not message.payload.get("run_id"):
            self.queue.nack(message.message_id, "unsupported queue message", requeue=False)
            raise ValueError(f"unsupported queue message: {message.kind}")
        try:
            result = self.runtime.execute_run(message.payload["run_id"])
        except Exception as exc:
            self.queue.nack(message.message_id, str(exc), requeue=False)
            raise
        self.queue.ack(message.message_id)
        return result
