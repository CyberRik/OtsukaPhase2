"""Literal, LLM-free export of a chat answer's raw text to a downloadable file —
the same "give me the data I already have, unmodified" contract as a CSV export,
not a re-authored/synthesized document (that's the planner's `documents`
capability, which regathers evidence and lets the model rewrite it into slides).

Parses the same lightweight markdown convention the chat UI already renders
(`web/components/assistant/message.tsx`'s `AnswerMd`: `#`-headings, `-`/`*`
bullets, `---` rules) so the exported file's structure matches what the user
actually saw on screen.
"""
from __future__ import annotations

import re

from senpai.documents import registry, render

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_RULE_RE = re.compile(r"^-{3,}$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")


def _text_to_doc_spec(text: str, title: str) -> dict:
    sections: list[dict] = []
    current = {"heading": "", "body": []}

    def flush() -> None:
        if current["body"] or current["heading"]:
            sections.append({"heading": current["heading"], "body": list(current["body"])})

    for raw_line in (text or "").replace("\r", "").split("\n"):
        line = raw_line.strip()
        if not line or _RULE_RE.match(line):
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            current = {"heading": heading.group(1).strip(), "body": []}
            continue
        bullet = _BULLET_RE.match(line)
        current["body"].append(f"- {bullet.group(1).strip()}" if bullet else line)
    flush()

    if not sections:
        sections = [{"heading": "", "body": [(text or "").strip() or "(no content)"]}]

    return {"title": title or "Export", "subtitle": "", "sections": sections}


def export_text_as_docx(text: str, title: str = "", slug: str = "") -> dict:
    """Render `text` verbatim (parsed, not LLM-rewritten) to a .docx and register
    it for download. Returns the registry record (doc_id, filename, download_url)."""
    spec = _text_to_doc_spec(text, title)
    path = render.output_path("export", slug or title or "chat", "docx")
    render.render_docx(spec, path)
    return registry.register("export", path)
