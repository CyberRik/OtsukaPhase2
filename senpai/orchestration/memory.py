"""Cross-chat memory: durable, entity-anchored Observations.

We persist the JUDGMENTS a chat reached — not transcripts — keyed by `Subject`, so a
later chat about the same account/deal can reason from what we already concluded. This
is the token-cheap form of cross-chat memory: a handful of compact, cited observations
instead of whole histories.

This module is the storage SEAM, not the storage. The persistence layer's database
will be just another `ObservationStore` implementation; the JSONL stub here gives
working cross-chat memory *today* (it survives restarts) so the read/write path can be
built and tested before the DB exists. Callers hold the Protocol, so swapping backends
changes nothing upstream.

Deliberately minimal for this stub: no indexing, no dedup, no supersession — just
`put` and `by_subject` ordered newest-first. Those richer semantics belong in the DB
implementation, not here; adding them to a flat file would only be rewritten.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from dataclasses import replace

from senpai import config
from senpai.orchestration.reason import EntityRef, Observation


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ObservationStore(Protocol):
    """The seam. `put` persists one anchored observation; `by_subject` returns the
    most recent observations about an entity. The DB implements exactly this."""

    def put(self, obs: Observation) -> None: ...

    def by_subject(self, subject: EntityRef, *, limit: int = 20) -> list[Observation]: ...


class JsonlObservationStore:
    """Append-only JSONL stub — one observation per line. `by_subject` scans and
    filters by subject key, newest-first (`as_of` desc). Unindexed: fine for demo
    scale and for proving the cross-chat path; the DB replaces it behind the Protocol.

    Thread-safe via a coarse lock — the chat engine fans tools out across worker
    threads, so writes can race. Reads tolerate partial/malformed lines (a crash
    mid-write must not poison the whole store)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def put(self, obs: Observation) -> None:
        if obs.subject is None:
            return  # unanchored → not cross-chat addressable; nothing to key on
        if not obs.as_of:
            obs = replace(obs, as_of=_now_iso())  # stamp when the judgment was reached
        line = json.dumps(obs.as_dict(), ensure_ascii=False)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def by_subject(self, subject: EntityRef, *, limit: int = 20) -> list[Observation]:
        hits = [o for o in self._read_all()
                if o.subject is not None and o.subject.key == subject.key]
        hits.sort(key=lambda o: o.as_of, reverse=True)
        return hits[:limit]

    def _read_all(self) -> list[Observation]:
        with self._lock:
            if not self._path.exists():
                return []
            lines = self._path.read_text(encoding="utf-8").splitlines()
        out: list[Observation] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Observation.from_dict(json.loads(line)))
            except (ValueError, TypeError, KeyError):
                continue  # skip malformed/partial lines; a stub must be robust
        return out


_DEFAULT: ObservationStore | None = None


def default_store() -> ObservationStore:
    """Process-wide store at the configured JSONL path. Lazy so import stays cheap and
    tests can construct their own JsonlObservationStore against a tmp path instead."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = JsonlObservationStore(config.OBSERVATIONS_PATH)
    return _DEFAULT


# --- write-side: anchor this turn's observations to the entity in focus --------

def subject_from_focus(focus) -> EntityRef | None:
    """Turn the session's resolved entity ([[SessionFocus]]) into an observation
    anchor. Prefer the deal (most specific — it also carries its customer); fall back
    to a standalone account. A bare quote with no entity id can't anchor → None, so
    the observation stays unstored rather than being filed under nothing."""
    if focus is None:
        return None
    if getattr(focus, "deal_id", None):
        return EntityRef(type="deal", id=focus.deal_id,
                         display=focus.customer_name or "")
    if getattr(focus, "customer_id", None):
        return EntityRef(type="account", id=focus.customer_id,
                         display=focus.customer_name or "")
    return None


def remember_observations(observations, *, subject: EntityRef | None = None,
                          store: ObservationStore | None = None) -> int:
    """Persist a turn's observations to cross-chat memory, anchored to `subject`.

    The write hook the Reasoner calls with the observations it *already* extracted for
    Compose — so persistence adds no extra LLM call. When `subject` is omitted it is
    derived from the live conversation via [[SessionFocus]] (lazy import: keeps this
    module free of a tools dependency). No subject → nothing is addressable, so we
    skip (returns 0) rather than filing unanchored judgments. Already-anchored
    observations keep their own subject. Returns the number persisted."""
    if not observations:
        return 0
    if subject is None:
        from senpai.tools.focus import session_focus  # lazy: avoid orchestration→tools coupling at import
        subject = subject_from_focus(session_focus())
    if subject is None:
        return 0
    store = store or default_store()
    n = 0
    for obs in observations:
        anchored = obs if obs.subject is not None else replace(obs, subject=subject)
        store.put(anchored)
        n += 1
    return n
