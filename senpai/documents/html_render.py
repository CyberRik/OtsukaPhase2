"""HTML/CSS/JS deck renderer — the visual source of truth for generated decks.

The general deck tool authors a rich, typed `deck_spec` (senpai/documents/author.py)
and this module turns it into ONE self-contained HTML file: inline CSS + a tiny inline
JS for keyboard nav, no external assets. That HTML is what the user sees, is downloadable
as-is, and is the input to both exports in senpai/documents/export.py:

  * PDF   — Chromium `page.pdf()` of this HTML (pixel-perfect).
  * PPTX  — Chromium reads each slide's layout, we bake the decorative layer into a
            background image (text made transparent) and place NATIVE, EDITABLE
            python-pptx text boxes on top. That pass depends on the DOM contract below.

Export contract (do not break without updating export.py):
  * Every slide is `<section class="slide" data-index="N"> … </section>`, sized exactly
    SLIDE_W × SLIDE_H CSS px, positioned relative.
  * Every run of user text that should stay editable in PPTX is wrapped in a LEAF element
    carrying the class `pptx-text` (no pptx-text inside another pptx-text). The exporter
    reads each such element's box + computed font to emit a textbox, so pptx-text must sit
    on the text itself, never on an element that also carries a background/border/fill
    (those would be blanked when the text is hidden) — e.g. table cells wrap their text in
    an inner <span class="pptx-text">.
  * Purely decorative marks (accent bars, cards, SVG charts, icons, page numbers) are NOT
    pptx-text; they get rasterized into the slide background.

Layout vocabulary handled: title, section, bullets, two_column, stat, quote, table
(comparison), timeline, chart, image_caption. Unknown layouts fall back to bullets.
"""
from __future__ import annotations

import html
import math

from senpai.documents.render import _STAT_RE  # single source of the figure-highlight rule

# Slide geometry in CSS px. 16:9. Kept in one place because export.py converts these
# same numbers to EMU when placing the background picture and text boxes.
SLIDE_W = 1280
SLIDE_H = 720

# Brand palette — mirrors the constants in render.py so HTML and native-PPTX fallback
# look like the same deck. (render.py stores them as RGB tuples; here as CSS hex.)
_BLUE = "#0055A4"
_TEAL = "#14B8A6"
_AMBER = "#E07A2E"
_NAVY = "#00205A"    # the "pull the number out" navy (render._STAT_NAVY)
_GRAY = "#6B7280"
_INK = "#1A2330"     # body text
_MUTE = "#5B6672"
_PINK = "#E13365"    # source template's punchline-pink, used only for delta callouts
_GRID = "#EDF1F5"    # recessive gridlines
_BASE = "#D6DEE7"    # axis baseline


def render_html(deck_spec: dict, lang: str = "ja") -> str:
    """Render a deck spec to a complete, self-contained HTML document string."""
    slides = deck_spec.get("slides") or []
    if not slides:
        slides = [{"layout": "title", "title": deck_spec.get("title", "Presentation"),
                   "subtitle": deck_spec.get("subtitle", "")}]

    body = [_render_slide(spec, i) for i, spec in enumerate(slides)]
    deck_title = html.escape(str((slides[0] or {}).get("title") or "Presentation"))

    return _DOC.format(title=deck_title, lang=html.escape(lang or "ja"),
                       css=_CSS, slides="\n".join(body), js=_JS)


# --------------------------------------------------------------------------------------
# Figure highlighting: wrap grounded numeric/price/percentage tokens in bold navy, the
# same convention render._add_styled_runs applies natively. Input is plain text.
def _fig(text: str) -> str:
    parts = _STAT_RE.split(str(text or ""))
    out = []
    for i, part in enumerate(parts):
        if not part:
            continue
        esc = html.escape(part)
        out.append(f'<b class="fig">{esc}</b>' if i % 2 == 1 else esc)
    return "".join(out)


def _esc(text) -> str:
    return html.escape(str(text or ""))


# --------------------------------------------------------------------------------------
# Per-layout slide renderers. Each returns the inner HTML of one <section class="slide">.
def _render_slide(spec: dict, index: int) -> str:
    layout = str(spec.get("layout") or "bullets").lower()
    fn = _LAYOUTS.get(layout, _slide_bullets)
    inner = fn(spec)
    # Speaker notes ride on the slide as an attribute so export.py can attach them to the
    # PPTX notes pane without needing the original spec.
    notes = _esc(spec.get("notes"))
    return (f'<section class="slide slide--{_esc(layout)}" data-index="{index}" '
            f'data-notes="{notes}">'
            f'{inner}'
            f'<div class="pageno">{index + 1:02d}</div>'
            f'</section>')


def _head(spec: dict) -> str:
    """Shared slide header (kicker rule + title + underline) for content layouts."""
    title = _fig(spec.get("title"))
    if not title:
        return ""
    return (f'<div class="head"><div class="kicker"></div>'
            f'<h2 class="head-title pptx-text">{title}</h2>'
            f'<div class="head-rule"></div></div>')


def _body(spec: dict, inner: str) -> str:
    """Wrap a content layout: header on top, body vertically centred in the remaining
    space so slides read full and balanced instead of top-heavy."""
    return f'{_head(spec)}<div class="body">{inner}</div>'


def _bullet_items(bullets) -> str:
    # pptx-text sits on the text span, not the <li>, so the exported textbox excludes the
    # decorative marker (baked into the slide background).
    return "".join(
        f'<li><span class="mk"></span><span class="li-txt pptx-text">{_fig(b)}</span></li>'
        for b in (bullets or []))


def _slide_title(spec: dict) -> str:
    title = _fig(spec.get("title"))
    subtitle = _fig(spec.get("subtitle"))
    sub = f'<p class="t-sub pptx-text">{subtitle}</p>' if subtitle else ""
    return (f'<div class="corner-mark"></div>'
            f'<div class="title-wrap">'
            f'<div class="t-accent"></div>'
            f'<h1 class="t-title pptx-text">{title}</h1>'
            f'{sub}'
            f'</div>')


def _slide_section(spec: dict) -> str:
    title = _fig(spec.get("title"))
    subtitle = _fig(spec.get("subtitle"))
    sub = f'<p class="s-sub pptx-text">{subtitle}</p>' if subtitle else ""
    return (f'<div class="s-glow"></div>'
            f'<div class="section-wrap">'
            f'<div class="s-rule"></div>'
            f'<h2 class="s-title pptx-text">{title}</h2>'
            f'{sub}'
            f'</div>')


def _slide_bullets(spec: dict) -> str:
    return _body(spec, f'<ul class="bullets">{_bullet_items(spec.get("bullets"))}</ul>')


def _slide_two_column(spec: dict) -> str:
    blocks = []
    for c in (spec.get("columns") or [])[:2]:
        heading = _fig(c.get("heading"))
        h = f'<h3 class="col-h pptx-text">{heading}</h3>' if heading else ""
        blocks.append(f'<div class="col"><div class="col-bar"></div>{h}'
                      f'<ul class="bullets">{_bullet_items(c.get("bullets"))}</ul></div>')
    return _body(spec, f'<div class="cols">{"".join(blocks)}</div>')


def _slide_stat(spec: dict) -> str:
    cards = []
    for st in (spec.get("stats") or [])[:4]:
        value = _fig(st.get("value"))
        label = _fig(st.get("label"))
        cards.append(f'<div class="stat-card"><div class="stat-accent"></div>'
                     f'<div class="stat-val pptx-text">{value}</div>'
                     f'<div class="stat-lab pptx-text">{label}</div></div>')
    note = _fig(spec.get("note"))
    note_html = f'<p class="stat-note pptx-text">{note}</p>' if note else ""
    return _body(spec, f'<div class="stats">{"".join(cards)}</div>{note_html}')


def _slide_quote(spec: dict) -> str:
    quote = _fig(spec.get("quote"))
    attribution = _fig(spec.get("attribution"))
    attr = f'<div class="q-attr pptx-text">— {attribution}</div>' if attribution else ""
    return (f'<div class="quote-wrap">'
            f'<div class="q-mark">“</div>'
            f'<blockquote class="q-text pptx-text">{quote}</blockquote>'
            f'{attr}'
            f'</div>')


def _slide_table(spec: dict) -> str:
    tbl = spec.get("table") or {}
    headers = tbl.get("headers") or []
    rows = tbl.get("rows") or []
    thead = ""
    if headers:
        cells = "".join(f'<th><span class="pptx-text">{_fig(h)}</span></th>' for h in headers)
        thead = f'<thead><tr>{cells}</tr></thead>'
    body_rows = []
    for r in rows:
        cells = "".join(f'<td><span class="pptx-text">{_fig(c)}</span></td>' for c in r)
        body_rows.append(f'<tr>{cells}</tr>')
    return _body(spec, f'<table class="cmp">{thead}<tbody>{"".join(body_rows)}</tbody></table>')


def _slide_timeline(spec: dict) -> str:
    phases = spec.get("phases") or []
    n = len(phases)
    boxes = []
    for i, p in enumerate(phases):
        label = _fig(p.get("label"))
        duration = _fig(p.get("duration"))
        detail = _fig(p.get("detail"))
        dur = f'<div class="tl-dur pptx-text">{duration}</div>' if duration else ""
        det = f'<div class="tl-det pptx-text">{detail}</div>' if detail else ""
        arrow = '<div class="tl-arrow">›</div>' if i < n - 1 else ""
        boxes.append(f'<div class="tl-item"><div class="tl-box">'
                     f'<div class="tl-step">STEP {i + 1:02d}</div>'
                     f'<div class="tl-label pptx-text">{label}</div>{dur}{det}</div>{arrow}</div>')
    return _body(spec, f'<div class="timeline">{"".join(boxes)}</div>')


def _slide_chart(spec: dict) -> str:
    chart = spec.get("chart") or {}
    ctype = str(chart.get("type") or "bar").lower()
    svg = _svg_doughnut(chart) if ctype in ("doughnut", "donut", "pie") else _svg_bar(chart)
    return _body(spec, f'<div class="chart-wrap">{svg}</div>')


def _slide_image_caption(spec: dict) -> str:
    url = str(spec.get("image_url") or "").strip()
    caption = _fig(spec.get("caption"))
    cap = f'<p class="ic-cap pptx-text">{caption}</p>' if caption else ""
    if url and (url.startswith("data:") or url.startswith("https://")):
        media = f'<div class="ic-media"><img src="{_esc(url)}" alt=""/></div>'
    else:
        # No trustworthy image URL: render a branded callout of the bullets instead of
        # inventing a stock photo (matches render.py's no-stock-image discipline).
        media = (f'<div class="ic-callout">'
                 f'<ul class="bullets">{_bullet_items(spec.get("bullets"))}</ul></div>')
    return _body(spec, f'<div class="ic-wrap">{media}{cap}</div>')


_LAYOUTS = {
    "title": _slide_title,
    "section": _slide_section,
    "bullets": _slide_bullets,
    "content": _slide_bullets,
    "two_column": _slide_two_column,
    "stat": _slide_stat,
    "quote": _slide_quote,
    "table": _slide_table,
    "comparison": _slide_table,
    "timeline": _slide_timeline,
    "chart": _slide_chart,
    "image_caption": _slide_image_caption,
}


# --------------------------------------------------------------------------------------
# Inline SVG charts — deterministic, dependency-free (no matplotlib, no JS chart lib), so
# they rasterize crisply into the PPTX background. Following the dataviz mark specs: thin
# marks anchored to a baseline, rounded data-ends, recessive gridlines, direct value
# labels (never a legend-only chart), a de-emphasized gray baseline series vs a navy
# emphasis series, and a punchline delta badge on two-value comparisons.
def _svg_bar(chart: dict) -> str:
    cats = chart.get("categories") or []
    series = chart.get("series") or []
    vals = [float(v) for v in ((series[0].get("values") if series else []) or [])]
    labels = chart.get("value_labels") or []
    n = min(len(cats), len(vals))
    if n == 0:
        return ""
    maxv = max(vals[:n]) or 1.0
    left, top, row_h, bar_max, bar_h = 300, 40, 96, 660, 52
    plot_bottom = top + row_h * n
    parts = [f'<svg viewBox="0 0 1120 {plot_bottom + 40}" class="chart-svg" '
             f'preserveAspectRatio="xMidYMid meet">']
    # recessive vertical gridlines + baseline
    for g in (0.25, 0.5, 0.75, 1.0):
        gx = left + bar_max * g
        parts.append(f'<line x1="{gx:.0f}" y1="{top - 8}" x2="{gx:.0f}" y2="{plot_bottom}" '
                     f'stroke="{_GRID}" stroke-width="2"/>')
    parts.append(f'<line x1="{left}" y1="{top - 8}" x2="{left}" y2="{plot_bottom}" '
                 f'stroke="{_BASE}" stroke-width="3"/>')
    for i in range(n):
        v = vals[i]
        y = top + i * row_h + (row_h - bar_h) / 2
        w = max(6, bar_max * (v / maxv))
        color = _NAVY if i == n - 1 else "#9AA7B4"
        lab = labels[i] if i < len(labels) else f"{v:g}"
        parts.append(f'<text x="{left - 24}" y="{y + bar_h / 2 + 10}" text-anchor="end" '
                     f'class="c-cat">{_esc(cats[i])}</text>')
        parts.append(f'<rect x="{left}" y="{y:.0f}" width="{w:.0f}" height="{bar_h}" rx="8" '
                     f'fill="{color}"/>')
        parts.append(f'<text x="{left + w + 18:.0f}" y="{y + bar_h / 2 + 11}" '
                     f'class="c-val">{_esc(lab)}</text>')
    # delta badge for a two-value before→after comparison
    if n == 2 and vals[0]:
        pct = round((1 - vals[1] / vals[0]) * 100)
        if pct != 0:
            arrow = "▼" if pct > 0 else "▲"
            parts.append(f'<text x="{left + bar_max * 0.5:.0f}" y="{plot_bottom + 30}" '
                         f'text-anchor="middle" class="c-delta">{arrow} {abs(pct)}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_doughnut(chart: dict) -> str:
    cats = chart.get("categories") or []
    series = chart.get("series") or []
    vals = [float(v) for v in ((series[0].get("values") if series else []) or [])]
    total = sum(vals) or 1.0
    if not vals:
        return ""
    colors = [_NAVY, _TEAL, _AMBER, "#9AA7B4", _BLUE]
    cx, cy, r, sw = 210, 210, 150, 62
    circ = 2 * math.pi * r
    gap = 6  # 2px surface gap between segments (scaled to viewBox)
    parts = [f'<svg viewBox="0 0 720 420" class="chart-svg" preserveAspectRatio="xMidYMid meet">']
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#EEF2F6" '
                 f'stroke-width="{sw}"/>')
    off = 0.0
    for i, v in enumerate(vals):
        frac = v / total
        dash = max(0.0, circ * frac - gap)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="{colors[i % len(colors)]}" stroke-width="{sw}" '
                     f'stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
                     f'stroke-dashoffset="{-off:.2f}" stroke-linecap="butt" '
                     f'transform="rotate(-90 {cx} {cy})"/>')
        off += circ * frac
    # hero number in the hole: the headline segment's share
    hero = round(100 * vals[0] / total)
    parts.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" class="c-hero">{hero}%</text>')
    if cats:
        parts.append(f'<text x="{cx}" y="{cy + 34}" text-anchor="middle" '
                     f'class="c-herolab">{_esc(cats[0])}</text>')
    # legend with values
    ly = 118
    for i, c in enumerate(cats):
        val = vals[i] if i < len(vals) else 0
        pct = round(100 * val / total)
        parts.append(f'<rect x="452" y="{ly - 20}" width="22" height="22" rx="6" '
                     f'fill="{colors[i % len(colors)]}"/>')
        parts.append(f'<text x="486" y="{ly - 2}" class="c-leg">{_esc(c)}</text>')
        parts.append(f'<text x="700" y="{ly - 2}" text-anchor="end" class="c-legval">{pct}%</text>')
        ly += 52
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------------------
_CSS = f"""
:root {{
  --blue: {_BLUE}; --teal: {_TEAL}; --amber: {_AMBER}; --navy: {_NAVY};
  --gray: {_GRAY}; --ink: {_INK}; --mute: {_MUTE};
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ background: #E6EAF0; }}
body {{
  font-family: "Noto Sans JP", "Noto Sans CJK JP", "Yu Gothic", "Hiragino Sans",
               "Meiryo", system-ui, sans-serif;
  color: var(--ink); -webkit-font-smoothing: antialiased;
  display: flex; flex-direction: column; align-items: center; gap: 28px; padding: 28px 0;
}}
.slide {{
  position: relative; width: {SLIDE_W}px; height: {SLIDE_H}px; flex: 0 0 auto;
  background: #fff; overflow: hidden;
  box-shadow: 0 8px 30px rgba(0,32,96,.14); border-radius: 6px;
  padding: 62px 82px; display: flex; flex-direction: column;
}}
/* brand ribbon along the top of every content slide */
.slide::after {{
  content: ''; position: absolute; left: 0; top: 0; width: 100%; height: 7px;
  background: linear-gradient(90deg, var(--navy) 0%, var(--blue) 55%, var(--teal) 100%);
}}
.slide--title::after, .slide--section::after, .slide--quote::after {{ display: none; }}
.fig {{ color: var(--navy); font-weight: 800; }}
.pageno {{
  position: absolute; right: 34px; bottom: 26px; font-size: 15px; font-weight: 700;
  color: #B4BDC8; letter-spacing: .12em;
}}

/* shared content header + centred body */
.head {{ margin-bottom: 26px; flex: 0 0 auto; }}
.kicker {{ width: 30px; height: 6px; border-radius: 3px; background: var(--teal); margin-bottom: 14px; }}
.head-title {{ font-size: 40px; font-weight: 800; color: var(--navy); line-height: 1.2; }}
.head-rule {{ display: none; }}
.body {{ flex: 1 1 auto; display: flex; flex-direction: column; justify-content: center; min-height: 0; }}

/* title slide */
.slide--title {{ justify-content: center; }}
.corner-mark {{ position: absolute; right: -120px; top: -120px; width: 360px; height: 360px;
  border-radius: 50%; background: radial-gradient(circle at 30% 30%, rgba(20,184,166,.16), rgba(0,85,164,.05)); }}
.t-accent {{ width: 128px; height: 12px; border-radius: 6px;
  background: linear-gradient(90deg, var(--teal), var(--blue)); margin-bottom: 34px; }}
.t-title {{ font-size: 66px; font-weight: 900; color: var(--navy); line-height: 1.14; letter-spacing: -.01em; }}
.t-sub {{ font-size: 30px; color: var(--mute); margin-top: 26px; font-weight: 500; }}

/* section divider */
.slide--section {{
  background: linear-gradient(135deg, var(--navy) 0%, var(--blue) 100%);
  justify-content: center;
}}
.s-glow {{ position: absolute; left: -140px; bottom: -160px; width: 460px; height: 460px;
  border-radius: 50%; background: radial-gradient(circle, rgba(20,184,166,.30), transparent 62%); }}
.section-wrap {{ position: relative; }}
.s-rule {{ width: 128px; height: 12px; border-radius: 6px; background: var(--teal); margin-bottom: 30px; }}
.s-title {{ font-size: 62px; font-weight: 900; color: #fff; line-height: 1.15; }}
.s-sub {{ font-size: 26px; color: #C4D4EA; margin-top: 22px; font-weight: 500; }}

/* bullets */
.bullets {{ list-style: none; display: flex; flex-direction: column; gap: 24px; }}
.bullets li {{ display: flex; align-items: flex-start; gap: 20px; font-size: 28px; line-height: 1.42; }}
.mk {{ flex: 0 0 auto; width: 14px; height: 14px; border-radius: 4px;
  background: linear-gradient(135deg, var(--teal), var(--blue)); margin-top: 13px; }}
.li-txt {{ flex: 1; }}

/* two column */
.cols {{ display: flex; gap: 40px; }}
.col {{ flex: 1; background: #F6F8FB; border: 1px solid #E7ECF2; border-radius: 16px; padding: 32px 34px; }}
.col-bar {{ width: 56px; height: 8px; border-radius: 4px; background: var(--blue); margin-bottom: 18px; }}
.col-h {{ font-size: 28px; font-weight: 800; color: var(--navy); margin-bottom: 20px; }}
.col .bullets li {{ font-size: 23px; gap: 15px; }}
.col .mk {{ margin-top: 10px; width: 11px; height: 11px; }}

/* stat */
.stats {{ display: flex; gap: 30px; }}
.stat-card {{
  position: relative; flex: 1; background: #F6F8FB; border: 1px solid #E7ECF2;
  border-radius: 18px; padding: 46px 26px 40px; text-align: center; overflow: hidden;
}}
.stat-accent {{ position: absolute; left: 0; top: 0; width: 100%; height: 8px;
  background: linear-gradient(90deg, var(--teal), var(--blue)); }}
.stat-val {{ font-size: 74px; font-weight: 900; color: var(--navy); line-height: 1; white-space: nowrap; }}
.stat-val .fig {{ color: var(--navy); }}
.stat-lab {{ font-size: 23px; color: var(--mute); margin-top: 18px; font-weight: 600; }}
.stat-note {{ font-size: 20px; color: var(--gray); margin-top: 30px; }}

/* quote */
.slide--quote {{ justify-content: center; }}
.quote-wrap {{ position: relative; padding-left: 26px; }}
.q-mark {{ font-size: 170px; color: var(--teal); line-height: .6; font-family: Georgia, serif; height: 78px; }}
.q-text {{ font-size: 44px; font-weight: 700; color: var(--navy); line-height: 1.34; margin-top: 8px; }}
.q-attr {{ font-size: 26px; color: var(--mute); margin-top: 30px; font-weight: 600; }}

/* comparison table */
.cmp {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 25px;
  box-shadow: 0 2px 14px rgba(0,32,96,.07); border-radius: 12px; overflow: hidden; }}
.cmp th {{ background: var(--navy); color: #fff; font-weight: 700; text-align: left; padding: 20px 24px; }}
.cmp td {{ padding: 18px 24px; border-bottom: 1px solid #E7ECF2; color: var(--ink); }}
.cmp tbody tr:nth-child(even) {{ background: #F6F8FB; }}
.cmp tbody tr:last-child td {{ border-bottom: none; }}
.cmp td:first-child, .cmp th:first-child {{ font-weight: 700; }}
/* Cell text spans fill the column so the exported editable text box is column-wide and
   short values (prices, codes) don't wrap when re-rendered in PowerPoint's wider font. */
.cmp th .pptx-text, .cmp td .pptx-text {{ display: block; width: 100%; }}

/* timeline */
.timeline {{ display: flex; align-items: stretch; }}
.tl-item {{ display: flex; align-items: center; flex: 1; }}
.tl-box {{
  flex: 1; border-radius: 14px; padding: 26px 22px; min-height: 210px; background: #F6F8FB;
  border: 1px solid #E1E8F0; border-top: 6px solid var(--blue);
  display: flex; flex-direction: column; gap: 8px;
}}
.tl-step {{ font-size: 15px; font-weight: 800; letter-spacing: .12em; color: var(--teal); }}
.tl-label {{ font-size: 26px; font-weight: 800; color: var(--navy); margin-top: 2px; }}
.tl-dur {{ font-size: 21px; font-weight: 700; color: var(--blue); }}
.tl-det {{ font-size: 18px; color: var(--mute); line-height: 1.35; }}
.tl-arrow {{ color: var(--blue); font-size: 46px; font-weight: 800; padding: 0 10px; flex: 0 0 auto; }}

/* chart */
.chart-wrap {{ display: flex; justify-content: center; align-items: center; height: 100%; }}
.chart-svg {{ max-width: 100%; max-height: 100%; }}
.c-cat {{ font-size: 27px; fill: var(--ink); font-weight: 600; font-family: "Noto Sans JP", sans-serif; }}
.c-val {{ font-size: 30px; fill: var(--navy); font-weight: 800; font-family: "Noto Sans JP", sans-serif; }}
.c-delta {{ font-size: 34px; fill: {_PINK}; font-weight: 900; font-family: "Noto Sans JP", sans-serif; }}
.c-hero {{ font-size: 68px; fill: var(--navy); font-weight: 900; font-family: "Noto Sans JP", sans-serif; }}
.c-herolab {{ font-size: 22px; fill: var(--mute); font-weight: 600; font-family: "Noto Sans JP", sans-serif; }}
.c-leg {{ font-size: 26px; fill: var(--ink); font-weight: 600; font-family: "Noto Sans JP", sans-serif; }}
.c-legval {{ font-size: 26px; fill: var(--navy); font-weight: 800; font-family: "Noto Sans JP", sans-serif; }}

/* image / callout */
.ic-wrap {{ display: flex; flex-direction: column; gap: 22px; height: 100%; }}
.ic-media {{ flex: 1; overflow: hidden; border-radius: 14px; }}
.ic-media img {{ width: 100%; height: 100%; object-fit: cover; }}
.ic-callout {{ flex: 1; background: #F6F8FB; border: 1px solid #E7ECF2; border-left: 8px solid var(--teal);
  border-radius: 14px; padding: 38px 44px; display: flex; align-items: center; }}
.ic-cap {{ font-size: 22px; color: var(--mute); font-weight: 600; }}

/* on-screen nav only — hidden in print/export */
.nav {{ position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
        background: rgba(0,32,96,.85); color: #fff; border-radius: 999px;
        padding: 8px 18px; font-size: 14px; letter-spacing: .04em; z-index: 10; }}

@page {{ size: {SLIDE_W}px {SLIDE_H}px; margin: 0; }}
@media print {{
  html, body {{ background: #fff; }}
  body {{ gap: 0; padding: 0; }}
  .slide {{ box-shadow: none; border-radius: 0; page-break-after: always; break-after: page; }}
  .nav {{ display: none; }}
}}
"""

_JS = """
(function () {
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var i = 0;
  function go(n) { i = Math.max(0, Math.min(slides.length - 1, n));
    slides[i].scrollIntoView({behavior: 'smooth', block: 'center'}); }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') { go(i + 1); e.preventDefault(); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { go(i - 1); e.preventDefault(); }
  });
})();
"""

_DOC = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{slides}
<div class="nav">← → で移動</div>
<script>{js}</script>
</body>
</html>
"""
