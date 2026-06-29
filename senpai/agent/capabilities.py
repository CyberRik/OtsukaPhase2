"""Crew gather capability.

The crew agents' prompts consume the STRING outputs of the existing deterministic
tools (query_spr, find_similar_deals, search_notes, …). To preserve those artifacts
byte-for-byte while running the gather on the orchestration engine, we expose one
thin capability that runs any existing tool by name through `impl.dispatch` — the
single shared tool layer. No retrieval logic is reimplemented or duplicated; this is
purely the engine's adapter onto the tools the crew already used.

(M1's research capabilities emit *structured* evidence for the research summarizer;
the crew prompts were written against *tool strings*, so they share the engine and
the underlying `store`/`impl` layer rather than the M1 capability classes. Capability
convergence is the post-migration simplification step, not M2.)
"""
from __future__ import annotations

from typing import Any, Mapping

from senpai.orchestration import CapabilityRegistry, ExecContext
from senpai.orchestration.evidence import Evidence
from senpai.orchestration.metadata import CapabilityMetadata, OperationKind
from senpai.tools import impl


class ToolCapability:
    """Runs one deterministic tool (`impl.dispatch(op, inputs)`) and returns its
    string output as evidence. `op` is the tool name; `impl.dispatch` never raises."""
    name = "tool"
    metadata = CapabilityMetadata(OperationKind.COMPUTE)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        text = impl.dispatch(op, dict(inputs))
        status = "error" if text.startswith("[error]") else "ok"
        return Evidence.ok({"text": text}, citations=[op], status=status)


def build_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(ToolCapability())
    return reg
