"""Account context synthesis workflow.

Synthesizes all available information about the customer into one persistent
`AccountContext` object, then answers follow-up questions purely from that
synthesized context — no re-fetching of the underlying data.

    from senpai.matsuda import build_account_context
    ctx = build_account_context("C28")       # one synthesis, persisted in `ctx`
    print(ctx.answer("What are the biggest risks?"))   # answered from `ctx`
    open("report.md", "w").write(ctx.to_markdown())    # inspectable report
"""
from __future__ import annotations

from senpai.matsuda.context import DealView, AccountContext
from senpai.matsuda.synthesize import build_account_context

__all__ = ["AccountContext", "DealView", "build_account_context"]
