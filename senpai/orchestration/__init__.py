"""Senpai orchestration spine (M0).

The smallest layer that runs a dependency graph of deterministic *capabilities*
in parallel, collects their structured output into an immutable *evidence bundle*,
and streams a single, capability-agnostic event timeline while it works.

Mental model (read these three files, in order, to understand the whole thing):

    capability.py   what work looks like  — Task, ExecutionPlan, Capability, ExecContext
    evidence.py     what work produces    — Evidence (one fragment), EvidenceBundle
    engine.py       how work runs         — ExecutionEngine: one threaded scheduler loop

The pipeline this spine is the middle of:

    plan ──► ExecutionEngine ──► EvidenceBundle ──► [Reducer] ──► [Reasoner] ──► artifact
              (this package)                          stub          stub          (route's job)

A *capability* owns one domain (CRM, Knowledge, Filesystem, Email, Calendar,
Browser, Office, …). It does deterministic work, returns structured Evidence, and
NEVER reasons or orchestrates. Adding a new capability is: write one class with a
`run()` method, register it. The engine never changes.

Nothing here calls an LLM or touches the network — it is GPU-free and unit-testable
on its own (`python -m senpai.orchestration` runs a self-test).
"""
from __future__ import annotations

from senpai.orchestration.capability import (
    Capability,
    CapabilityRegistry,
    ExecContext,
    ExecutionPlan,
    Task,
    TaskPolicy,
)
from senpai.orchestration.engine import ExecutionEngine
from senpai.orchestration.evidence import Evidence, EvidenceBundle, Timing
from senpai.orchestration import events

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "ExecContext",
    "ExecutionPlan",
    "Task",
    "TaskPolicy",
    "ExecutionEngine",
    "Evidence",
    "EvidenceBundle",
    "Timing",
    "events",
]
