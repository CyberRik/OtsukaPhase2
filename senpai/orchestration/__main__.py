"""Self-test: `python -m senpai.orchestration`.

GPU-free, no network. Exercises the whole spine with toy capabilities:
parallel execution, dependency ordering, runtime DAG expansion (fan-out),
retries, partial failure (skip vs fail_run), and the EvidenceBundle + EchoReasoner.

Prints the event timeline, then asserts the outcomes and reports PASS/FAIL.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Mapping

# Windows consoles default to cp1252; the timeline uses box-drawing/JP characters.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from senpai.orchestration import (
    CapabilityRegistry,
    ExecContext,
    ExecutionEngine,
    ExecutionPlan,
    Task,
    TaskPolicy,
)
from senpai.orchestration.evidence import Evidence
from senpai.orchestration.reason import EchoReasoner
from senpai.orchestration.reducer import PassthroughReducer


# --- toy capabilities -------------------------------------------------------
class SleepyCapability:
    """A READ that sleeps briefly then returns its inputs as data — lets us prove
    independent tasks overlap in wall-clock time."""
    name = "sleepy"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        ctx.emit(f"working on {inputs.get('label', op)}")
        time.sleep(0.2)
        return Evidence.ok({"label": inputs.get("label", op)},
                           citations=[f"toy:{inputs.get('label', op)}"])


class FlakyCapability:
    """Fails on its first attempt, succeeds on retry — proves the retry policy."""
    name = "flaky"

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        with self._lock:
            first = ctx.task_id not in self._seen
            self._seen.add(ctx.task_id)
        if first:
            raise RuntimeError("transient blip")
        return Evidence.ok({"recovered": True})


class BoomCapability:
    """Always fails — proves partial failure degrades the run (on_failure='skip')."""
    name = "boom"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        raise ValueError("permanent failure")


class FanoutCapability:
    """Discovers N items and expands the DAG with one downstream task per item —
    the runtime-breadth pattern the Endo Kogyo query needs."""
    name = "fanout"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        n = int(inputs.get("n", 3))
        children = [
            Task(id=f"item-{i}", capability="sleepy", inputs={"label": f"item-{i}"},
                 group="items", summary=f"process item {i}")
            for i in range(n)
        ]
        ctx.expand(children)
        return Evidence.ok({"discovered": n}, citations=[f"discovered:{n}"])


def main() -> int:
    reg = CapabilityRegistry()
    for cap in (SleepyCapability(), FlakyCapability(), BoomCapability(), FanoutCapability()):
        reg.register(cap)

    plan = ExecutionPlan(tasks=(
        # three independent reads (should overlap) ...
        Task(id="a", capability="sleepy", inputs={"label": "A"}, group="research"),
        Task(id="b", capability="sleepy", inputs={"label": "B"}, group="research"),
        Task(id="c", capability="sleepy", inputs={"label": "C"}, group="research"),
        # ... a dependent that waits on a & b ...
        Task(id="d", capability="sleepy", inputs={"label": "D"},
             depends_on=frozenset({"a", "b"}), group="research", summary="needs A+B"),
        # ... a flaky read that recovers on retry ...
        Task(id="r", capability="flaky", policy=TaskPolicy(retries=1), group="coach"),
        # ... a hard failure that must NOT kill the run (skip) ...
        Task(id="x", capability="boom", group="coach", summary="expected to fail"),
        # ... and a fan-out that grows the graph at runtime.
        Task(id="f", capability="fanout", inputs={"n": 3}, group="discover"),
    ))

    events: list[dict] = []
    t0 = time.time()
    bundle = ExecutionEngine(reg, max_workers=8).run(plan, events.append)
    wall = time.time() - t0

    print("── event timeline ──")
    for e in events:
        print(f"  [{e['seq']:>2}] {e['type']:<16} "
              f"{ {k: v for k, v in e.items() if k not in ('type','run_id','seq','ts')} }")

    view = PassthroughReducer().reduce(bundle)
    print("\n── EchoReasoner over bundle ──")
    print("".join(EchoReasoner().stream(view)))

    # --- assertions ---------------------------------------------------------
    types = [e["type"] for e in events]
    ok = bundle.get("a").status == "ok"
    checks = {
        "all seed+expanded tasks recorded": len(bundle.fragments) == 7 + 3,
        "fan-out grew the plan": "plan.expanded" in types,
        "flaky task recovered via retry": bundle.get("r").status == "ok"
                                          and bundle.get("r").timing.attempts == 2,
        "hard failure degraded, did not abort": bundle.get("x").status == "error",
        "run completed (not cancelled)": "run.completed" in types,
        "dependent ran after deps": bundle.get("d").status == "ok",
        "parallelism (7 seed tasks well under serial 0.2s each)": wall < 1.0,
        "evidence carries citations": "toy:A" in bundle.citations(),
        "reasoner view drops errors": all(f["status"] != "error"
                                          for f in view["fragments"]),
    }
    print("\n── checks ──")
    passed = True
    for name, good in checks.items():
        print(f"  {'PASS' if good else 'FAIL'}  {name}")
        passed = passed and good
    print(f"\nwall={wall:.2f}s  fragments={len(bundle.fragments)}  "
          f"events={len(events)}")
    print("RESULT:", "PASS" if passed and ok else "FAIL")
    return 0 if passed and ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
