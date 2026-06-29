"""What work produces: one immutable Evidence fragment per task, collected into an
immutable EvidenceBundle.

Principles that let this scale to many capabilities:
  * Immutable + append-only. Each task writes exactly one fragment keyed by its
    task id; fragments never overwrite each other -> no locks, order-independent.
  * No reconciliation. Two sources disagreeing is signal for the Reasoner, not
    something the bundle resolves. Provenance is always preserved.
  * `data` is structured JSON — never markdown. `citations` are human-renderable
    handles ("SPR D003", "Playbook PB12", "file://…#slide3") the artifact can quote.

Engine-owned fields (task_id, capability, op, group, timing) are filled in by the
engine, so a capability only supplies `data` / `citations` / `confidence` /
`provenance` via the `ok` / `empty` / `error` constructors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class Timing:
    started: float = 0.0
    ended: float = 0.0
    duration: float = 0.0
    attempts: int = 0
    cache_hit: bool = False


@dataclass(frozen=True)
class Evidence:
    """One task's structured result. Build with `Evidence.ok/empty/error`; the
    engine stamps the identity/timing fields."""
    status: str                       # "ok" | "partial" | "empty" | "error"
    data: Mapping[str, Any] = field(default_factory=dict)
    citations: tuple[str, ...] = ()
    confidence: float = 1.0
    provenance: Mapping[str, Any] = field(default_factory=dict)
    # filled by the engine:
    task_id: str = ""
    capability: str = ""
    op: str = ""
    group: str = "default"
    timing: Timing = field(default_factory=Timing)

    # -- capability-facing constructors (identity/timing left for the engine) --
    @classmethod
    def ok(cls, data: Mapping[str, Any], *, citations: Iterable[str] = (),
           confidence: float = 1.0, provenance: Mapping[str, Any] | None = None,
           status: str = "ok") -> "Evidence":
        return cls(status=status, data=dict(data), citations=tuple(citations),
                   confidence=confidence, provenance=dict(provenance or {}))

    @classmethod
    def empty(cls, *, provenance: Mapping[str, Any] | None = None) -> "Evidence":
        return cls.ok({}, status="empty", confidence=0.0, provenance=provenance)

    @classmethod
    def error(cls, message: str, *, provenance: Mapping[str, Any] | None = None) -> "Evidence":
        prov = dict(provenance or {})
        prov["error"] = message
        return cls.ok({}, status="error", confidence=0.0, provenance=prov)


@dataclass(frozen=True)
class EvidenceBundle:
    """All fragments from one run, keyed by task id. Offers ordered views (by
    capability / group) and a canonical `to_reasoner_view` the Reducer/Reasoner
    consume. Frozen once the engine returns it."""
    run_id: str
    fragments: Mapping[str, Evidence] = field(default_factory=dict)

    def get(self, task_id: str) -> Evidence | None:
        return self.fragments.get(task_id)

    def _ordered(self) -> list[Evidence]:
        # Deterministic order (capability, task_id) so synthesis is reproducible
        # even though tasks complete in nondeterministic wall-clock order.
        return sorted(self.fragments.values(), key=lambda e: (e.capability, e.task_id))

    def by_capability(self, name: str) -> list[Evidence]:
        return [e for e in self._ordered() if e.capability == name]

    def by_group(self, group: str) -> list[Evidence]:
        return [e for e in self._ordered() if e.group == group]

    def usable(self) -> list[Evidence]:
        return [e for e in self._ordered() if e.status in ("ok", "partial")]

    def citations(self) -> list[str]:
        return [c for e in self._ordered() for c in e.citations]

    def to_reasoner_view(self) -> dict:
        """Canonical, structured view fed to reasoning. Errors are dropped (their
        absence is reported separately); everything else is passed through. This is
        the seam the Reducer replaces when evidence outgrows the context budget."""
        return {
            "run_id": self.run_id,
            "fragments": [
                {"capability": e.capability, "op": e.op, "status": e.status,
                 "confidence": e.confidence, "citations": list(e.citations),
                 "data": dict(e.data)}
                for e in self._ordered() if e.status != "error"
            ],
        }
