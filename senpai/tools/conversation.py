"""Per-turn conversation context for grounding-aware tools.

The document-generation tools (generate_pptx / generate_docx) author their content
from a `grounding` string. On their own they only ever saw CRM + Web — so a request
that references something already established earlier in the SAME conversation (a
company read from a local file two turns ago, a deal we just looked up) came back
ungrounded, and the model hallucinated a generic deck under the wrong company name.

The chat loop publishes the live conversation here right before it dispatches a
round of tools; the doc tools read it to ground on what is actually in focus.

A ContextVar (not a module global) so concurrent turns can't cross-contaminate.
The execution engine runs each tool inside `contextvars.copy_context()`
(engine.py), so a value set in the loop before `_ENGINE.run` is visible to the
tool even though it executes on a worker thread. The loop sets it within the same
synchronous block as the engine run (no generator `yield` in between), so the
Starlette thread-hop that breaks cross-`next()` ContextVars does not apply here.
"""
from __future__ import annotations

import contextvars

_CONVO: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "senpai_turn_convo", default=None)


def set_conversation(convo: list[dict] | None) -> None:
    """Publish the live conversation (system/user/assistant/tool messages) for the
    tools about to run. A shallow copy so later in-place mutation by the loop does
    not retroactively change what a mid-flight tool sees."""
    _CONVO.set(list(convo) if convo else None)


def conversation() -> list[dict]:
    """The conversation published for the current turn (empty list when none)."""
    return _CONVO.get() or []
