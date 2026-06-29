"""The single, capability-agnostic event vocabulary for Workspace execution.

The engine is the only source of these. They describe the *DAG lifecycle*, never a
domain — so adding Filesystem/Email/Browser needs zero new event types. A /crew
(multi-lane) and a /research (single stream) view are the same event stream
rendered with different grouping (`group` + `summary` are the only layout drivers).

Every event the engine emits carries: type, run_id, seq (monotonic), ts (epoch).

Routes may translate these to the legacy SSE names during migration; new front-end
code consumes this vocabulary directly. The constants below are the contract.
"""
from __future__ import annotations

from typing import Callable

# A sink the engine pushes fully-formed event dicts into.
Emit = Callable[[dict], None]

# -- run lifecycle --
RUN_STARTED = "run.started"        # {groups: [str], planned_count: int}
RUN_COMPLETED = "run.completed"    # {completed: int, failed: int}
RUN_CANCELLED = "run.cancelled"    # {completed: int}

# -- plan growth (runtime fan-out) --
PLAN_EXPANDED = "plan.expanded"    # {added_count: int, total_count: int}

# -- task lifecycle --
TASK_STARTED = "task.started"      # {task_id, capability, op, group, summary}
TASK_PROGRESS = "task.progress"    # {task_id, message}   (capability sub-step)
TASK_EVIDENCE = "task.evidence"    # {task_id, status, confidence, citations: [str]}
TASK_COMPLETED = "task.completed"  # {task_id, duration, status}
TASK_RETRYING = "task.retrying"    # {task_id, attempt, reason}
TASK_FAILED = "task.failed"        # {task_id, reason, recoverable}
GROUP_COMPLETED = "group.completed"  # {group}   (UI lane done — crew's "agent done")

# -- post-gather stages (engine does NOT emit these in M0; reserved for the route /
#    Reducer / Reasoner so the contract is stable from day one) --
REDUCE_STARTED = "reduce.started"
REDUCE_COMPLETED = "reduce.completed"
REASON_STARTED = "reason.started"
REASON_DELTA = "reason.delta"      # {text}
REASON_COMPLETED = "reason.completed"  # {markdown}
ARTIFACT_CREATED = "artifact.created"  # {kind, ref, download_url}
APPROVAL_REQUIRED = "approval.required"  # {gate_id, preview}   (future WRITE gate)
AUTH_REQUIRED = "auth.required"    # {capability, auth_url}      (future external caps)
