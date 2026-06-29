"""What work looks like: the plan (a DAG of Tasks) and the Capability contract.

A `Task` is one node in the graph — a request to run one operation of one
capability. An `ExecutionPlan` is the set of tasks plus their dependency edges. A
`Capability` is the thing that actually does the work for a task; it receives an
`ExecContext` (its only window to the outside world) and returns an `Evidence`.

Design rules that keep this additive:
  * A Task is an immutable plan node. It carries NO result — outcomes live in the
    EvidenceBundle, keyed by task id. (Plan and result stay separate.)
  * A Capability does deterministic domain work only. No reasoning, no markdown, no
    orchestration, no calling other capabilities. Structured Evidence in, out.
  * Policy (timeout/retries/failure-handling) lives in one small TaskPolicy with
    sane defaults, so the common case is a one-line Task.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:  # avoid an import cycle — only needed for type hints
    from senpai.orchestration.evidence import Evidence


# --- Task policy ------------------------------------------------------------
@dataclass(frozen=True)
class TaskPolicy:
    """How the engine should run a task. Defaults suit a fast, idempotent READ;
    override per-task only when a capability needs it (e.g. retries=0 for an
    effectful WRITE so it is never auto-repeated)."""
    timeout_s: float = 30.0           # advisory deadline, surfaced via ctx.remaining()
    retries: int = 0                  # extra attempts on exception (READ-safe ops only)
    on_failure: str = "skip"          # "skip" (degrade, keep going) | "fail_run" (cancel)


DEFAULT_POLICY = TaskPolicy()


# --- Task -------------------------------------------------------------------
@dataclass(frozen=True)
class Task:
    """One node in the execution DAG: run `op` of `capability` with `inputs`,
    after every task in `depends_on` has reached a terminal state. `group` and
    `summary` are presentation-only (which lane / one-liner the UI timeline shows)."""
    id: str
    capability: str
    op: str = ""
    inputs: Mapping[str, Any] = field(default_factory=dict)
    depends_on: frozenset[str] = field(default_factory=frozenset)
    policy: TaskPolicy = DEFAULT_POLICY
    group: str = "default"
    summary: str = ""


# --- Plan -------------------------------------------------------------------
@dataclass(frozen=True)
class ExecutionPlan:
    """A gather DAG: just the tasks (edges are the tasks' `depends_on`). Reasoning
    is NOT part of the plan — the route reduces + reasons over the resulting bundle.
    The graph may still grow at runtime via `ctx.expand(...)`; `validate()` only
    checks the seed."""
    tasks: tuple[Task, ...]

    def validate(self) -> None:
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task ids in plan")
        known = set(ids)
        for t in self.tasks:
            missing = t.depends_on - known
            if missing:
                raise ValueError(f"task {t.id!r} depends on unknown task(s): {sorted(missing)}")
        self._check_acyclic()

    def _check_acyclic(self) -> None:
        deps = {t.id: set(t.depends_on) for t in self.tasks}
        WHITE, GREY, BLACK = 0, 1, 2
        color = dict.fromkeys(deps, WHITE)

        def visit(n: str) -> None:
            color[n] = GREY
            for m in deps[n]:
                if color[m] == GREY:
                    raise ValueError(f"dependency cycle through task {m!r}")
                if color[m] == WHITE:
                    visit(m)
            color[n] = BLACK

        for n in deps:
            if color[n] == WHITE:
                visit(n)


# --- Execution context (a capability's only handle to the outside) ----------
@dataclass
class ExecContext:
    """Handed to `Capability.run`. Everything a capability may touch beyond its own
    inputs goes through here — so capabilities never import the engine, and new
    cross-cutting concerns (auth/connections, tracing) are added as fields later
    without changing any capability signature.

      deps     evidence from this task's upstream dependencies, by task id
      emit     report a human sub-step (-> a task.progress event)
      expand   request new tasks (runtime DAG growth / fan-out)
      cancel   cooperative cancellation — long ops should check `cancelled()`
      deadline absolute time the task should finish by (advisory)
    """
    task_id: str
    inputs: Mapping[str, Any]
    deps: Mapping[str, "Evidence"]
    emit: Callable[[str], None]
    expand: Callable[[list[Task]], None]
    cancel: threading.Event
    deadline: float

    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def remaining(self) -> float:
        import time
        return max(0.0, self.deadline - time.time())


# --- Capability contract ----------------------------------------------------
@runtime_checkable
class Capability(Protocol):
    """One domain of deterministic work. Stable interface: implement `run` and set
    `name`. `run` dispatches on `op` if the domain has several operations (CRM:
    'lookup_deal' / 'list_proposals'); single-operation capabilities ignore `op`."""
    name: str

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> "Evidence":
        ...


class UnknownCapability(KeyError):
    pass


class CapabilityRegistry:
    """Name -> Capability. The engine resolves a task's capability through this; a
    new capability becomes available by registering it here."""

    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def register(self, cap: Capability) -> Capability:
        self._caps[cap.name] = cap
        return cap

    def get(self, name: str) -> Capability:
        try:
            return self._caps[name]
        except KeyError:
            raise UnknownCapability(name) from None

    def __contains__(self, name: str) -> bool:
        return name in self._caps

    def names(self) -> list[str]:
        return sorted(self._caps)
