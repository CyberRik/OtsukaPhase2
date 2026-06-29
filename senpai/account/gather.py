"""Run the account plan on the engine and return the same (context_text, meta) the
route used from `build_account_context` directly — so `/account/.../commentary` is
unchanged on the wire and in artifact.
"""
from __future__ import annotations

from typing import Callable

from senpai.account.capabilities import build_registry
from senpai.account.plan import account_plan
from senpai.orchestration import ExecutionEngine

_REGISTRY = build_registry()
_NOOP: Callable[[dict], None] = lambda _ev: None

_NOT_FOUND_TEXT = "NO MATCHING ACCOUNT FOUND. Do not invent any account facts."


def gather_account_context(customer_id: str, lang: str = "ja", today=None,
                           emit: Callable[[dict], None] | None = None) -> tuple[str, dict]:
    bundle = ExecutionEngine(_REGISTRY).run(
        account_plan(customer_id, lang=lang, today=today), emit or _NOOP)
    ev = bundle.get("account_context")
    if ev is None or ev.status == "error":
        # Capability failure -> degrade to the package's own not-found shape (the
        # route then streams an account_not_found unavailable, never crashing).
        meta = {"has_account": False, "customer": None, "customer_id": customer_id,
                "score": None, "band": None}
        return _NOT_FOUND_TEXT, meta
    return ev.data["context_text"], ev.data["meta"]
