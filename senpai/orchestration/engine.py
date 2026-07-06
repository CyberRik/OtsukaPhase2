"""How work runs: one threaded scheduler loop over the execution DAG.

The whole engine is `ExecutionEngine.run`. Read it top to bottom:

  1. Set up bookkeeping (task table, per-task state, collected fragments).
  2. Loop:
       - absorb any tasks a running capability asked to add (`ctx.expand`)
       - submit every PENDING task whose dependencies are all terminal
       - wait for the next task to finish; record its evidence, emit events
       - if a "fail_run" task failed, cancel and drain
     until nothing is pending and nothing is running.
  3. Return the immutable EvidenceBundle.

Boring on purpose: a ThreadPoolExecutor (the OpenAI client and store are blocking,
so threads — not asyncio — parallelize them with no rewrite), plain dicts for
state, cooperative cancellation via a threading.Event. No framework.

Capabilities supply only the domain part of an Evidence (`ok/empty/error`); the
engine stamps identity + timing. A capability raising is caught here and turned
into an error fragment — one bad capability can never crash a run.
"""
from __future__ import annotations

import concurrent.futures as cf
import contextvars
import itertools
import threading
import time
import uuid
from dataclasses import replace

from senpai.orchestration import events
from senpai.orchestration.capability import CapabilityRegistry, ExecContext, ExecutionPlan, Task
from senpai.orchestration.evidence import Evidence, EvidenceBundle, Timing

_TERMINAL = ("done", "failed", "skipped")


class ExecutionEngine:
    def __init__(self, registry: CapabilityRegistry, max_workers: int = 8) -> None:
        self.registry = registry
        self.max_workers = max_workers

    def run(self, plan: ExecutionPlan, emit: events.Emit) -> EvidenceBundle:
        plan.validate()
        run_id = uuid.uuid4().hex[:8]
        seq = itertools.count()
        emit_lock = threading.Lock()

        def out(etype: str, **fields) -> None:
            # Serialize emission: capabilities emit progress from worker threads.
            with emit_lock:
                emit({"type": etype, "run_id": run_id, "seq": next(seq),
                      "ts": time.time(), **fields})

        tasks: dict[str, Task] = {t.id: t for t in plan.tasks}
        state: dict[str, str] = {tid: "pending" for tid in tasks}
        fragments: dict[str, Evidence] = {}

        cancel = threading.Event()
        expand_buf: list[Task] = []
        expand_lock = threading.Lock()

        def expand(new: list[Task]) -> None:
            with expand_lock:
                expand_buf.extend(new)

        groups: dict[str, set[str]] = {}
        for t in tasks.values():
            groups.setdefault(t.group, set()).add(t.id)
        groups_done: set[str] = set()

        def absorb_expanded() -> None:
            with expand_lock:
                batch, expand_buf[:] = expand_buf[:], []
            added = 0
            for t in batch:
                if t.id in tasks:
                    continue  # idempotent: ignore a duplicate id
                tasks[t.id] = t
                state[t.id] = "pending"
                groups.setdefault(t.group, set()).add(t.id)
                added += 1
            if added:
                out(events.PLAN_EXPANDED, added_count=added, total_count=len(tasks))

        def deps_terminal(t: Task) -> bool:
            return all(state.get(d) in _TERMINAL for d in t.depends_on)

        def check_group(g: str) -> None:
            if g in groups_done:
                return
            if all(state.get(i) in _TERMINAL for i in groups[g]):
                groups_done.add(g)
                out(events.GROUP_COMPLETED, group=g)

        out(events.RUN_STARTED, groups=sorted(groups), planned_count=len(tasks))

        with cf.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures: dict[cf.Future, str] = {}
            submitted: set[str] = set()

            while True:
                absorb_expanded()

                # Submit every ready task. Under cancellation, ready tasks are
                # marked skipped instead of run (cooperative shutdown).
                for tid, t in list(tasks.items()):
                    if tid in submitted or state[tid] != "pending":
                        continue
                    if cancel.is_set():
                        state[tid] = "skipped"
                        check_group(t.group)
                        continue
                    if not deps_terminal(t):
                        continue
                    submitted.add(tid)
                    state[tid] = "running"
                    deps_ev = {d: fragments[d] for d in t.depends_on if d in fragments}
                    # Emit started BEFORE submitting, so a task's started event always
                    # precedes any progress the worker emits (clean UI timeline).
                    out(events.TASK_STARTED, task_id=tid, capability=t.capability,
                        op=t.op, group=t.group, summary=t.summary)
                    # Run the worker in a COPY of the submitting thread's context so
                    # per-turn ContextVar buffers (generated-document chips in
                    # documents/registry.py, retrieval traces) set by the caller before
                    # run() are visible inside the worker — they share the same buffer
                    # list object, so a tool's register()/trace there surfaces on the
                    # main thread's drain(). Without this, threaded execution silently
                    # drops the same-turn download chip and retrieval trace.
                    ctx = contextvars.copy_context()
                    fut = ex.submit(ctx.run, self._exec_task, t, deps_ev, out, expand, cancel)
                    futures[fut] = tid

                if not futures:
                    absorb_expanded()
                    stuck = [tid for tid in tasks
                             if tid not in submitted and state[tid] == "pending"]
                    if not stuck:
                        break
                    # Nothing running and nothing ready: remaining tasks have an
                    # unsatisfiable dependency (a failed/skipped upstream they truly
                    # needed). Skip them rather than hang.
                    for tid in stuck:
                        state[tid] = "skipped"
                        out(events.TASK_FAILED, task_id=tid,
                            reason="unresolved_dependency", recoverable=False)
                        check_group(tasks[tid].group)
                    continue

                done, _ = cf.wait(futures, return_when=cf.FIRST_COMPLETED)
                for fut in done:
                    tid = futures.pop(fut)
                    ev = fut.result()  # _exec_task never raises
                    fragments[tid] = ev
                    state[tid] = "failed" if ev.status == "error" else "done"
                    out(events.TASK_EVIDENCE, task_id=tid, status=ev.status,
                        confidence=ev.confidence, citations=list(ev.citations))
                    # `data` rides along so a live SSE consumer can render this
                    # task's result the moment it lands, instead of waiting for the
                    # whole run to finish and re-deriving it from the final bundle
                    # (Evidence.data is already documented as forward-able JSON).
                    out(events.TASK_COMPLETED, task_id=tid,
                        duration=ev.timing.duration, status=ev.status, data=dict(ev.data))
                    if ev.status == "error" and tasks[tid].policy.on_failure == "fail_run":
                        cancel.set()
                        out(events.TASK_FAILED, task_id=tid,
                            reason=str(ev.provenance.get("error", "")), recoverable=False)
                    check_group(tasks[tid].group)

                if cancel.is_set():
                    # Drain whatever is still running, then stop scheduling.
                    for fut in list(futures):
                        tid = futures.pop(fut)
                        ev = fut.result()
                        fragments[tid] = ev
                        state[tid] = "failed" if ev.status == "error" else "done"
                        check_group(tasks[tid].group)
                    break

        bundle = EvidenceBundle(run_id=run_id, fragments=dict(fragments))
        completed = sum(1 for s in state.values() if s == "done")
        failed = sum(1 for s in state.values() if s == "failed")
        if cancel.is_set():
            out(events.RUN_CANCELLED, completed=completed)
        else:
            out(events.RUN_COMPLETED, completed=completed, failed=failed)
        return bundle

    # -- one task: resolve capability, run with retries, stamp identity/timing --
    def _exec_task(self, task: Task, deps_ev: dict, out: events.Emit,
                   expand, cancel: threading.Event) -> Evidence:
        started = time.time()
        deadline = started + task.policy.timeout_s

        def finish(ev: Evidence, attempts: int) -> Evidence:
            timing = Timing(started=started, ended=time.time(),
                            duration=round(time.time() - started, 3),
                            attempts=attempts, cache_hit=False)
            return replace(ev, task_id=task.id, capability=task.capability,
                           op=task.op, group=task.group, timing=timing)

        try:
            cap = self.registry.get(task.capability)
        except Exception as e:  # unknown capability — fail this task, not the run
            return finish(Evidence.error(f"{type(e).__name__}: {e}"), attempts=0)

        ctx = ExecContext(
            task_id=task.id, inputs=task.inputs, deps=deps_ev,
            emit=lambda msg: out(events.TASK_PROGRESS, task_id=task.id, message=msg),
            expand=expand, cancel=cancel, deadline=deadline,
        )

        attempts = 0
        last_err = ""
        while True:
            attempts += 1
            if cancel.is_set():
                return finish(Evidence.error("cancelled"), attempts)
            try:
                ev = cap.run(task.op, dict(task.inputs), ctx)
                return finish(ev, attempts)
            except Exception as e:  # noqa: BLE001 — a capability must never crash the run
                last_err = f"{type(e).__name__}: {e}"
                if attempts <= task.policy.retries and not cancel.is_set():
                    out(events.TASK_RETRYING, task_id=task.id,
                        attempt=attempts, reason=last_err)
                    time.sleep(min(0.5 * attempts, 2.0))
                    continue
                return finish(Evidence.error(last_err), attempts)
