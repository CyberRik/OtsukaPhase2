"""Demo-specific Matsuda synthesis workflow.

A self-contained slice that, when "Matsuda" is mentioned, synthesizes *all*
available information about the customer into one persistent `MatsudaContext`
object, then answers follow-up questions purely from that synthesized context —
no re-fetching of the underlying data.

Deliberately narrow: it targets the Matsuda account (有限会社松田サービス /
株式会社松田建設) for validation first, reads only through the existing store /
scoring / flags / retrieval layers, and touches no other workflow (Review Coach,
junior/manager chat, research mode are all untouched).

    from senpai.matsuda import build_matsuda_context
    ctx = build_matsuda_context()            # one synthesis, persisted in `ctx`
    print(ctx.answer("What are the biggest risks?"))   # answered from `ctx`
    open("report.md", "w").write(ctx.to_markdown())    # inspectable report
"""
from __future__ import annotations

from senpai.matsuda.context import DealView, MatsudaContext
from senpai.matsuda.synthesize import build_matsuda_context

__all__ = ["MatsudaContext", "DealView", "build_matsuda_context"]
