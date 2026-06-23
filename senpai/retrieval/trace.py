"""Retrieval trace — the observability spine for the Retrieval Explorer.

Every retrieval surface (semantic notes, keyword knowledge, graph) records what it
returned into a per-turn buffer: source type, source id, customer, score, scope,
and whether it was account-restricted. The API drains the buffer after each tool
call and ships it to the UI, so grounding is debuggable: you can see exactly which
chunks — from which customer, at what score — reached the model.

Deterministic and dependency-free. Uses a ContextVar so concurrent requests don't
share a buffer. Recording is best-effort and must never break a tool call.
"""
from __future__ import annotations

import contextvars
from typing import Any

_BUFFER: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "retrieval_trace", default=None)


def record(source: str, *, scope: str = "all", items: list[dict] | None = None,
           **summary: Any) -> None:
    """Append one retrieval event. `source` is the retriever (e.g. 'notes_semantic',
    'knowledge_keyword', 'graph'); `scope` is 'account:<id>' or 'all'; `items` are
    the per-chunk records (id/customer/score/text). Extra kwargs are summary fields
    (query, mode, customer, n). Never raises."""
    try:
        buf = _BUFFER.get()
        if buf is None:
            return  # tracing not active for this turn — no-op
        buf.append({"source": source, "scope": scope,
                    "items": items or [], **summary})
    except Exception:  # noqa: BLE001 — observability must never break retrieval
        pass


def start() -> None:
    """Begin (or reset) tracing for the current context."""
    _BUFFER.set([])


def drain() -> list[dict]:
    """Return the events recorded since the last drain/start, then clear the buffer.
    Returns [] when tracing was never started."""
    buf = _BUFFER.get()
    if not buf:
        return []
    _BUFFER.set([])
    return buf
