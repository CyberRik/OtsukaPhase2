"""Extension seam: the Reducer interface (map-reduce compaction).

When a run gathers more evidence than the Reasoner's context can hold ("every
proposal, quote, PDF, email…"), a Reducer shrinks the bundle — typically by
summarizing per document/group — before final reasoning.

M0 ships only the pass-through: the reasoner view is used as-is. A real
`MapReduceReducer` lands when a capability (Filesystem/Office/Email) can actually
produce bundle-overflowing volume; it implements the same one method, so nothing
upstream changes.
"""
from __future__ import annotations

from typing import Protocol

from senpai.orchestration.evidence import EvidenceBundle


class Reducer(Protocol):
    def reduce(self, bundle: EvidenceBundle) -> dict:
        """Return a reasoner-ready view (same shape as `bundle.to_reasoner_view`)."""
        ...


class PassthroughReducer:
    """No-op: hand the full structured bundle to the reasoner unchanged."""

    def reduce(self, bundle: EvidenceBundle) -> dict:
        return bundle.to_reasoner_view()
