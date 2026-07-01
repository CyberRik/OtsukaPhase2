"""Workspace — sandboxed, read-only local document access as an orchestration
capability.

The first capability that reaches *outside* the seed database: it finds and reads
real local files (PDF/DOCX/PPTX/XLSX/TXT/MD) and returns their text as structured
Evidence into the same EvidenceBundle every other capability feeds. It is the first
production user of the engine's runtime DAG expansion — a single `find` fans out
into N parallel `extract` tasks via `ctx.expand`.

Strictly READ-ONLY and confined to `config.WORKSPACE_ROOT` (see `sandbox.py`). No
write/edit/delete operations exist here by design.
"""
from senpai.workspace.gather import gather_workspace_documents, workspace_evidence

__all__ = ["gather_workspace_documents", "workspace_evidence"]
