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
# The layout vocabulary the model may choose from, one per slide. This is the fix
# for "decks are just bullet points": the old schema only allowed {title, bullets},
# so every slide collapsed to a bullet list no matter how rich render.py/html_render
# could draw it. Each layout normalizes (in `_normalize_slide`) to an internal slide
# dict that html_render.py renders richly AND render.py can still fall back on — every
# non-title slide also carries a plain `bullets` text form so the native-pptx fallback
# (used only when the HTML→PPTX browser path is unavailable) never renders blank.
_SLIDE_SCHEMA = (
    '- {"layout":"section","title":str,"subtitle":str}  (a divider that opens a new part)\n'
    '- {"layout":"bullets","title":str,"bullets":[str,...]}  (3-6 short points)\n'
    '- {"layout":"two_column","title":str,"columns":['
    '{"heading":str,"bullets":[str,...]},{"heading":str,"bullets":[str,...]}]}\n'
    '- {"layout":"stat","title":str,"stats":[{"value":"42%","label":str},...]}  (1-3 big figures)\n'
    '- {"layout":"quote","quote":str,"attribution":str}\n'
    '- {"layout":"comparison","title":str,"headers":[str,...],"rows":[[str,...],...]}\n'
    '- {"layout":"timeline","title":str,"phases":['
    '{"label":str,"duration":str,"detail":str},...]}\n'
    '- {"layout":"chart","title":str,"chart":{"type":"bar","categories":[str,...],'
    '"series":[{"name":str,"values":[number,...]}],"value_labels":[str,...]}}\n'
)


def author_deck(prompt: str, grounding: str = "", lang: str = "ja",
                customer_scoped: bool = False) -> dict | None:
    """Author a render-ready deck spec from a free prompt. None when the LLM is
    unavailable (tool surfaces a 'needs model' message). `customer_scoped` is True
    when the deck is grounded on a resolved CRM customer — it picks the sales-pitch
    style guide regardless of that customer's current deal status (see
    playbook.deck_style_guide)."""
    if not _use_llm():
        return None
    instr = (
        "You are an executive presentation designer building a C-level, visually rich "
        "deck. Produce it as STRICT JSON only — no prose, no code fence.\n"
        'Top level: {"title": str, "subtitle": str, "slides": [slide, ...]}.\n'
        f"Use 6-{MAX_SLIDES} content slides. DESIGN FOR VISUAL VARIETY — a wall of bullet "
        "lists is a failure. For each slide pick the layout that best fits its message:\n"
        f"{_SLIDE_SCHEMA}"
        "Requirements: (1) include at least ONE chart and ONE comparison table and ONE "
        "stat slide whenever the topic can support them; (2) open sections with a "
        "'section' divider; (3) use 'stat' for headline numbers and 'chart' to show any "
        "trend, split or before/after; (4) no more than ~2 plain 'bullets' slides in the "
        "whole deck. Favor data-driven, graphical slides throughout.\n"
        "For charts, give real category labels and numeric values (type 'bar' for "
        "comparisons/rankings, 'doughnut' for a share/composition split).\n"
        f"Write in {'Japanese' if lang == 'ja' else 'English'}.\n"
        f"{playbook.deck_style_guide(customer_scoped)}\n"
        f"Topic / request: {prompt}\n"
        f"{_grounding_block(grounding)}")
    obj = _extract_json(_complete(instr) or "")
    if obj is None:
        # one repair retry
        obj = _extract_json(_complete("Return ONLY valid JSON for the deck.\n" + instr) or "")
    if obj is None:
        obj = {"title": prompt[:80], "subtitle": "", "slides": []}
    return _to_deck_spec(obj, prompt)


def _s(x) -> str:
    return str(x or "").strip()


def _slist(xs) -> list[str]:
    return [str(b).strip() for b in (xs or []) if str(b).strip()]


def _normalize_slide(s: dict) -> dict | None:
    """Map one authored slide to an internal render slide. Keeps field names the
    native renderer already understands (chart/table/timeline) and always attaches a
    `bullets` text form so render.render_pptx degrades safely for the richer layouts
    it does not draw natively. Returns None for unusable input."""
    if not isinstance(s, dict):
        return None
    layout = _s(s.get("layout")).lower() or "bullets"
    title = _s(s.get("title"))
    notes = _s(s.get("notes"))

    if layout == "section":
        subtitle = _s(s.get("subtitle"))
        return {"layout": "section", "title": title or subtitle, "subtitle": subtitle,
                "bullets": _slist([subtitle]), "notes": notes}

    if layout in ("stat", "kpi"):
        stats = []
        for st in (s.get("stats") or []):
            if isinstance(st, dict):
                value, label = _s(st.get("value")), _s(st.get("label"))
                if value or label:
                    stats.append({"value": value, "label": label})
        return {"layout": "stat", "title": title, "stats": stats, "note": _s(s.get("note")),
                "bullets": [f"{x['value']} — {x['label']}".strip(" —") for x in stats],
                "notes": notes}

    if layout == "quote":
        quote = _s(s.get("quote") or s.get("text"))
        attribution = _s(s.get("attribution") or s.get("author"))
        line = (f"「{quote}」" + (f" — {attribution}" if attribution else "")) if quote else ""
        return {"layout": "quote", "title": title, "quote": quote, "attribution": attribution,
                "bullets": [line] if line else [], "notes": notes}

    if layout in ("two_column", "twocolumn", "columns"):
        cols, flat = [], []
        for c in (s.get("columns") or [])[:2]:
            if isinstance(c, dict):
                col = {"heading": _s(c.get("heading")), "bullets": _slist(c.get("bullets"))}
                cols.append(col)
                if col["heading"]:
                    flat.append(col["heading"])
                flat += col["bullets"]
        return {"layout": "two_column", "title": title, "columns": cols,
                "bullets": flat, "notes": notes}

    if layout in ("comparison", "table"):
        tbl = s.get("table") if isinstance(s.get("table"), dict) else {}
        headers = _slist(tbl.get("headers") or s.get("headers"))
        rows = [[str(c).strip() for c in r]
                for r in (tbl.get("rows") or s.get("rows") or [])
                if isinstance(r, (list, tuple))]
        return {"layout": "table", "title": title, "table": {"headers": headers, "rows": rows},
                "bullets": [" / ".join(r) for r in rows if any(r)], "notes": notes}

    if layout == "timeline":
        phases = []
        for p in (s.get("phases") or []):
            if isinstance(p, dict):
                phases.append({"label": _s(p.get("label")), "duration": _s(p.get("duration")),
                               "detail": _s(p.get("detail"))})
        return {"layout": "timeline", "title": title, "phases": phases,
                "bullets": [f"{p['label']}（{p['duration']}）".replace("（）", "").strip()
                            for p in phases if p["label"]], "notes": notes}

    if layout == "chart":
        ch = s.get("chart") if isinstance(s.get("chart"), dict) else {}
        cats = _slist(ch.get("categories"))
        series = []
        for se in (ch.get("series") or []):
            if isinstance(se, dict):
                vals = []
                for v in (se.get("values") or []):
                    try:
                        vals.append(float(v))
                    except (TypeError, ValueError):
                        pass
                series.append({"name": _s(se.get("name")), "values": vals})
        return {"layout": "chart", "title": title,
                "chart": {"type": _s(ch.get("type")) or "bar", "categories": cats,
                          "series": series, "value_labels": _slist(ch.get("value_labels"))},
                "bullets": [], "notes": notes}

    if layout in ("image_caption", "image", "callout"):
        caption = _s(s.get("caption"))
        return {"layout": "image_caption", "title": title, "image_url": _s(s.get("image_url")),
                "caption": caption, "bullets": _slist(s.get("bullets")) or _slist([caption]),
                "notes": notes}

    # default: plain bullet slide
    return {"layout": "bullets", "title": title, "bullets": _slist(s.get("bullets")),
            "notes": notes}


def _to_deck_spec(obj: dict, prompt: str) -> dict:
    """Convert authored JSON to the internal deck spec (title slide + typed content
    slides) that html_render.py and render.render_pptx consume."""
    slides = [{
        "layout": "title",
        "title": str(obj.get("title") or prompt[:80] or "Presentation"),
        "subtitle": str(obj.get("subtitle") or ""),
    }]
    for s in (obj.get("slides") or [])[:MAX_SLIDES]:
        norm = _normalize_slide(s)
        if norm is not None:
            slides.append(norm)
    if len(slides) == 1:  # model gave a title but no content → one summary slide
        slides.append({"layout": "bullets", "title": "概要",
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
