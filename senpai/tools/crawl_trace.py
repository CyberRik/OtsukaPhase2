"""Crawl trace — per-turn buffer of pages visited by the `site_intel` tool.

Direct sibling of `senpai/retrieval/trace.py`: when `site_intel` runs *inside* the
chat ReAct loop it can't stream (a tool returns one string), so it records each page
it visited here. The chat loop drains this after the tool call — exactly as it already
drains the retrieval trace and `documents.registry` pending buffer — and re-emits the
pages as `crawl_page` SSE events so the browser-sim card can replay the browse.

The dedicated `/api/intel/crawl` endpoint bypasses this and passes a live `emit`
callback instead, for true real-time streaming.

ContextVar-backed (concurrent requests don't share a buffer); recording is best-effort
and must never break a crawl.
"""
from __future__ import annotations

import contextvars

_BUFFER: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "crawl_trace", default=None)


def start() -> None:
    """Begin (or reset) crawl tracing for the current context."""
    _BUFFER.set([])


def record(page: dict) -> None:
    """Append one visited-page record. No-op when tracing isn't active. Never raises."""
    try:
        buf = _BUFFER.get()
        if buf is None:
            return
        buf.append(page)
    except Exception:  # noqa: BLE001 — observability must never break a crawl
        pass


def drain() -> list[dict]:
    """Return pages recorded since the last start/drain, then clear. [] if inactive."""
    buf = _BUFFER.get()
    if not buf:
        return []
    _BUFFER.set([])
    return buf
