"""Generated-document registry — maps a doc_id to its file so the bridge can serve
it for download, and lets the chat loop attach the just-generated doc to a tool event.

Two layers:
  * `_DOCS`   — a process-lifetime dict (doc_id -> metadata incl. absolute path) the
                download endpoint (`GET /api/documents/{doc_id}`) looks up. It is
                deliberately NOT a ContextVar: the download is a separate request from
                the chat turn that created the file.
  * pending   — a per-turn ContextVar buffer (mirrors senpai/retrieval/trace.py) that
                the chat loop drains after each tool call to surface a `document`
                event. Best-effort; never raises.

Only files registered here can be downloaded — the endpoint never accepts a raw path.
"""
from __future__ import annotations

import contextvars
import uuid
from datetime import datetime
from pathlib import Path

# doc_id -> {"doc_id", "kind", "filename", "path", "deal_id", "created_at"}
_DOCS: dict[str, dict] = {}

# Per-turn buffer of doc records generated in the current request context.
_PENDING: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "documents_pending", default=None)


def start() -> None:
    """Begin (or reset) the per-turn pending buffer for the current context."""
    _PENDING.set([])


def register(kind: str, path: Path, deal_id: str | None = None) -> dict:
    """Record a generated file and return its public metadata. `kind` is the tool
    name (e.g. 'proposal', 'pptx'); `path` is the saved file. Adds the record to the
    download registry AND, if a turn buffer is active, to the pending buffer."""
    doc_id = uuid.uuid4().hex[:12]
    rec = {
        "doc_id": doc_id,
        "kind": kind,
        "filename": Path(path).name,
        "path": str(Path(path).resolve()),
        "deal_id": deal_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "download_url": f"/api/documents/{doc_id}",
    }
    _DOCS[doc_id] = rec
    try:
        buf = _PENDING.get()
        if buf is not None:
            buf.append(rec)
    except Exception:  # noqa: BLE001 — surfacing must never break a tool
        pass
    return rec


def drain() -> list[dict]:
    """Return docs registered since the last drain/start, then clear. [] if inactive."""
    buf = _PENDING.get()
    if not buf:
        return []
    _PENDING.set([])
    return buf


def get(doc_id: str) -> dict | None:
    """Look up a generated doc by id (for the download endpoint)."""
    return _DOCS.get(doc_id)
