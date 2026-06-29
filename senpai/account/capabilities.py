"""Account capability — the account-commentary gather on the orchestration engine.

The account read is already a gather → single-reasoner workflow: a deterministic
context package (`build_account_context`) feeds one LLM stream. M3 moves the gather
onto the engine without touching the package or the prompt, so the artifact is
identical. It is wrapped as a single capability (the context package is one composite
text+meta unit); decomposing it into the shared CRM/Health/Environment capabilities
is part of the later structured-capability convergence, not M3.
"""
from __future__ import annotations

from typing import Any, Mapping

from senpai.account.context import build_account_context
from senpai.orchestration import CapabilityRegistry, ExecContext
from senpai.orchestration.evidence import Evidence


class AccountContextCapability:
    """Builds the deterministic account-commentary context package as structured
    evidence. Same call, same (context_text, meta) output as before."""
    name = "account_context"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        text, meta = build_account_context(
            inputs["customer_id"], today=inputs.get("today"),
            lang=inputs.get("lang", "ja"))
        has_account = bool(meta.get("has_account"))
        ctx.emit("account found" if has_account else "no matching account")
        return Evidence.ok({"context_text": text, "meta": meta},
                           citations=[f"account:{inputs['customer_id']}"],
                           status="ok" if has_account else "empty")


def build_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(AccountContextCapability())
    return reg
