"""LLM spec authoring for the GENERAL document tools (generate_pptx / generate_docx).

Unlike the grounded proposal/ringisho pair, these build a document about *anything*
from a free prompt ("make a deck about GTA 6"). The model authors a strict-JSON spec
which render.py turns into the file. There is intentionally **no deterministic
fallback for arbitrary topics**: if the model is off/unreachable the tool tells the
user it needs the model rather than emitting a blank file.

`grounding` is optional context the caller already gathered (store facts and/or a
web_search result); the prompt instructs the model to use it and cite web sources,
and to never invent specific figures without a source.
"""
from __future__ import annotations

import json
import os
import re

from senpai.documents import playbook

MAX_SLIDES = 20
MAX_SECTIONS = 15


def _use_llm() -> bool:
    return os.environ.get("SENPAI_USE_LLM", "0").lower() not in ("0", "false", "", "no")


def _complete(prompt: str) -> str | None:
    try:
        from senpai.llm.client import simple_complete
        out = simple_complete([{"role": "user", "content": prompt}],
                              temperature=0.5, max_tokens=1800,
                              no_think=True, allow_fallback=False)
        return out.strip() or None
    except Exception:  # noqa: BLE001 — model down/timeout
        return None


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model response (handles code fences)."""
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _grounding_block(grounding: str) -> str:
    if not (grounding or "").strip():
        return "(参考情報なし。一般知識に基づいて作成してよい。)"
    return ("以下の参考情報を最優先で使うこと。Web出典がある場合は本文に出典を添えること。"
            "参考情報にない具体的な数値・固有名詞を創作しないこと。\n" + grounding.strip())


# --- PPTX -----------------------------------------------------------------------
def author_deck(prompt: str, grounding: str = "", lang: str = "ja") -> dict | None:
    """Author a render-ready deck spec from a free prompt. None when the LLM is
    unavailable (tool surfaces a 'needs model' message)."""
    if not _use_llm():
        return None
    instr = (
        "You are a presentation author. Produce a slide deck as STRICT JSON only — no "
        "prose, no code fence. Schema: "
        '{"title": str, "subtitle": str, '
        '"slides": [{"title": str, "bullets": [str, ...]}, ...]}. '
        f"Use 4-{MAX_SLIDES} content slides, 3-6 concise bullets each. "
        f"Write in {'Japanese' if lang == 'ja' else 'English'}.\n"
        f"{playbook.deck_style_guide()}\n"
        f"Topic / request: {prompt}\n"
        f"{_grounding_block(grounding)}")
    obj = _extract_json(_complete(instr) or "")
    if obj is None:
        # one repair retry
        obj = _extract_json(_complete("Return ONLY valid JSON for the deck.\n" + instr) or "")
    if obj is None:
        obj = {"title": prompt[:80], "subtitle": "", "slides": []}
    return _to_deck_spec(obj, prompt)


def _to_deck_spec(obj: dict, prompt: str) -> dict:
    """Convert authored JSON to render.render_pptx's spec (title slide + content)."""
    slides = [{
        "layout": "title",
        "title": str(obj.get("title") or prompt[:80] or "Presentation"),
        "subtitle": str(obj.get("subtitle") or ""),
    }]
    for s in (obj.get("slides") or [])[:MAX_SLIDES]:
        if not isinstance(s, dict):
            continue
        slides.append({
            "layout": "content",
            "title": str(s.get("title") or ""),
            "bullets": [str(b) for b in (s.get("bullets") or []) if str(b).strip()],
        })
    if len(slides) == 1:  # model gave a title but no content → one summary slide
        slides.append({"layout": "content", "title": "概要",
                       "bullets": [str(obj.get("subtitle") or prompt)]})
    return {"slides": slides, "_title": slides[0]["title"]}


# --- DOCX -----------------------------------------------------------------------
def author_doc(prompt: str, grounding: str = "", lang: str = "ja") -> dict | None:
    """Author a render-ready doc spec from a free prompt. None when LLM unavailable."""
    if not _use_llm():
        return None
    instr = (
        "You are a document author. Produce a document as STRICT JSON only — no prose, "
        "no code fence. Schema: "
        '{"title": str, "subtitle": str, '
        '"sections": [{"heading": str, "body": [str, ...]}, ...]}. '
        f"Use 3-{MAX_SECTIONS} sections; each body is a list of paragraphs. "
        f"Write in {'Japanese' if lang == 'ja' else 'English'}.\n"
        f"Topic / request: {prompt}\n"
        f"{_grounding_block(grounding)}")
    obj = _extract_json(_complete(instr) or "")
    if obj is None:
        obj = _extract_json(_complete("Return ONLY valid JSON for the document.\n" + instr) or "")
    if obj is None:
        obj = {"title": prompt[:80], "subtitle": "", "sections": []}
    return _to_doc_spec(obj, prompt)


def _to_doc_spec(obj: dict, prompt: str) -> dict:
    sections = []
    for s in (obj.get("sections") or [])[:MAX_SECTIONS]:
        if not isinstance(s, dict):
            continue
        body = s.get("body")
        if isinstance(body, str):
            body = [body]
        sections.append({"heading": str(s.get("heading") or ""),
                         "body": [str(p) for p in (body or []) if str(p).strip()]})
    if not sections:
        sections = [{"heading": "概要", "body": [str(obj.get("subtitle") or prompt)]}]
    title = str(obj.get("title") or prompt[:80] or "Document")
    return {"title": title, "subtitle": str(obj.get("subtitle") or ""),
            "sections": sections, "_title": title}
