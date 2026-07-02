"""Persistent copilot chat history — durable conversation transcripts.

The Senpai Workspace chat previously lived only in browser memory and vanished on
every tab reload. This module makes conversations durable so a rep can close the
tab and later reopen a past chat exactly where it left off (full-fidelity, including
skill/artifact cards).

Storage is a single SQLite file (stdlib ``sqlite3``, WAL mode) keyed by
``conversation_id``. It is DELIBERATELY SEPARATE from ``senpai.data.store``: chat is
written on every turn and grows unboundedly, so mixing it into store's single
``lru_cache`` (which ``reload()`` drops wholesale) would be a perf footgun. Here a
save/rename/delete is a single indexed row op — no full-file rewrite, no cache drop.

The ``blob`` column is an OPAQUE client-owned JSON transcript. The server only reads
the small header columns (for listing); it never parses the blob. Concurrency:
open-per-call short-lived connections (sidesteps ``check_same_thread`` under FastAPI's
sync threadpool) + WAL (concurrent readers, one writer) + a module lock around writes.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from senpai import config

# Serialize writers; WAL already allows concurrent readers, but a process-level lock
# keeps the open-per-call writers from racing on the single demo DB file.
_WRITE_LOCK = threading.Lock()
_INIT_DONE = False


def _now() -> str:
    """ISO8601 UTC timestamp (sortable as text — matches the updated_at index)."""
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    """Fresh short-lived connection. Cheap; avoids cross-thread reuse issues under
    FastAPI's worker threadpool. Rows come back as dicts via row_factory."""
    config.CHAT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.CHAT_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create the table + owner index if missing (idempotent). Runs once at import."""
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _WRITE_LOCK:
        if _INIT_DONE:  # re-check inside lock
            return
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    employee_id     TEXT NOT NULL,
                    role            TEXT NOT NULL,
                    title           TEXT NOT NULL,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    message_count   INTEGER NOT NULL,
                    blob            TEXT NOT NULL
                )
                """
            )
            # Owner + recency: powers the "my chats, newest first" list query cheaply.
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_conv_owner
                    ON conversations (employee_id, role, updated_at DESC)
                """
            )
            conn.commit()
        finally:
            conn.close()
        _INIT_DONE = True


_HEADER_COLS = (
    "conversation_id, employee_id, role, title, created_at, updated_at, message_count"
)


def list_conversations(employee_id: str, role: str) -> list[dict]:
    """Header rows (no blob) for one owner+role, newest first."""
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT {_HEADER_COLS} FROM conversations "
            "WHERE employee_id = ? AND role = ? ORDER BY updated_at DESC",
            (employee_id, role),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_conversation(conversation_id: str) -> dict | None:
    """Full row including the opaque ``blob``. None if not found."""
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT {_HEADER_COLS}, blob FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def upsert_conversation(
    conversation_id: str,
    employee_id: str,
    role: str,
    title: str,
    blob: str,
    message_count: int,
) -> dict:
    """Insert or update one conversation. Preserves ``created_at`` on update and
    always bumps ``updated_at``. Returns the resulting header dict. Last-write-wins."""
    init_db()
    now = _now()
    with _WRITE_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO conversations
                    (conversation_id, employee_id, role, title,
                     created_at, updated_at, message_count, blob)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    title         = excluded.title,
                    updated_at    = excluded.updated_at,
                    message_count = excluded.message_count,
                    blob          = excluded.blob
                """,
                (conversation_id, employee_id, role, title,
                 now, now, message_count, blob),
            )
            conn.commit()
        finally:
            conn.close()
    header = get_conversation(conversation_id) or {}
    header.pop("blob", None)
    return header


def rename_conversation(conversation_id: str, title: str) -> bool:
    """Set a new title. Returns True if a row was updated."""
    init_db()
    now = _now()
    with _WRITE_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? "
                "WHERE conversation_id = ?",
                (title, now, conversation_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def delete_conversation(conversation_id: str) -> bool:
    """Delete one conversation. Returns True if a row was removed."""
    init_db()
    with _WRITE_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# Create the schema at import so the first request doesn't race on it.
init_db()
