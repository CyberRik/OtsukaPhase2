"""Segment Intelligence — GraphRAG-style community summarization over SPR deals.

Partitions deals into Category × Industry "communities" and produces grounded,
aggregate reports (win rate, top failure modes, recommended plays) — the global /
thematic sensemaking layer that our local retrieval (semantic notes, graph
lookups) structurally can't serve. It answers questions like
「製造業のサーバー案件、なぜ負ける？」from real tallies, not from stuffing hundreds
of raw daily reports into the model's context.

Two layers, mirroring the rest of the codebase:
  * DETERMINISTIC (this module, GPU-free): the partition and every statistic are
    computed in Python from the store and the deal-health engine — no number is
    ever invented. A templated Japanese narrative is always produced, so a report
    is useful even with no model available.
  * NARRATIVE (senpai/graph/build_communities.py, offline/committed): an LLM writes
    prose over ONLY those stats, grounding-gated by `ungrounded_numbers`. If the
    committed `communities.json` exists we load its narratives; otherwise we fall
    back to rebuilding deterministically in-memory here.

Hierarchy: category → category×industry → deal. A thin leaf (few closed deals) is
skipped and represented by its parent category rollup, which aggregates every deal
in the category regardless.

Public API:
  build_reports(today=None)                      -> list[dict]   (deterministic)
  load_reports()                                 -> list[dict]   (committed or built)
  reload()                                       -> None
  select(query, category, industry, outcome, limit) -> list[dict]
  format_report(report)                          -> str          (compact, cited)
  allowed_numbers(report) / ungrounded_numbers(text, report)     (grounding gate)
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache

from senpai import config
from senpai.coach.cases import THEME_PRINCIPLES
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal

# Health-signal name → coaching theme, so a segment's dominant failure mode maps to
# the same validated principles the Coach uses (senpai.coach.cases.THEME_PRINCIPLES).
SIGNAL_THEME: dict[str, str] = {
    "missing_dm": "no_decision_maker",
    "stall_language": "stalled",
    "staleness": "stalled",
    "order_date_past": "stalled",
    "rank_regression": "stalled",
    "rank_age": "stalled",
    "low_activity": "discovery",
}

# Manager-facing Japanese labels for the health-signal names (scoring.Signal.name).
SIGNAL_LABEL: dict[str, str] = {
    "missing_dm": "決裁者が未特定",
    "stall_language": "日報の停滞サイン",
    "staleness": "接触の停滞",
    "order_date_past": "完了予定日の超過",
    "rank_regression": "ランク低下",
    "rank_age": "ランク滞留",
    "low_activity": "活動量の不足",
}

_NUM = re.compile(r"\d+")


def _outcome(rank: str | None) -> str:
    if rank in config.WON_RANKS:
        return "won"
    if rank in config.DEAD_RANKS:
        return "lost"
    return "open"


# ---------------------------------------------------------------------------
# Deterministic stats — the trustworthy core (no model involved).
# ---------------------------------------------------------------------------
def _principles_for(sig_counter: Counter) -> list[str]:
    """Validated principle ids for a segment's top failure signals (order-preserved,
    deduped) — the recommended play, grounded in human-approved knowledge."""
    ids: list[str] = []
    for name, _ in sig_counter.most_common(2):
        for pid in THEME_PRINCIPLES.get(SIGNAL_THEME.get(name, ""), []):
            if pid not in ids:
                ids.append(pid)
    return ids


def segment_stats(deals: list[dict], today: date) -> dict:
    """All-Python aggregate over one segment's deals. Failure signals are tallied on
    LOST deals (what went wrong); reliability flags on every deal. Returns a plain
    dict of numbers — the only thing an LLM narrative is allowed to reference."""
    n_won = n_lost = n_open = 0
    sig_counter: Counter = Counter()
    flag_counter: Counter = Counter()
    for d in deals:
        acts = store.activities_for_deal(d["deal_id"])
        health = score_deal(d, acts, today)
        for f in deal_flags(d, acts, health_band=health.band, today=today):
            flag_counter[f.name] += 1
        oc = _outcome(d.get("order_rank"))
        if oc == "won":
            n_won += 1
        elif oc == "lost":
            n_lost += 1
            for s in health.signals:
                sig_counter[s.name] += 1
        else:
            n_open += 1

    closed = n_won + n_lost
    return {
        "n_deals": len(deals),
        "n_won": n_won,
        "n_lost": n_lost,
        "n_open": n_open,
        "win_rate": round(n_won / closed, 3) if closed else None,
        "top_failure_signals": [{"signal": k, "count": v} for k, v in sig_counter.most_common(4)],
        "top_flags": [{"flag": k, "count": v} for k, v in flag_counter.most_common(4)],
        "recommended_principle_ids": _principles_for(sig_counter),
    }


def _narrative(category: str, industry: str, st: dict) -> str:
    """Deterministic templated Japanese summary — always grounded (uses only numbers
    that appear in `st`), so a report ships even with no model. build_communities.py
    may replace this with an LLM narrative that passes the same grounding gate."""
    scope = f"{category}×{industry}" if industry else f"{category}（カテゴリ全体）"
    parts = [f"【{scope}】案件{st['n_deals']}件"]
    if st["win_rate"] is not None:
        parts.append(f"（成約{st['n_won']}・失注{st['n_lost']}、勝率{round(st['win_rate'] * 100)}%）")
    if st["top_failure_signals"]:
        top = st["top_failure_signals"][0]
        label = SIGNAL_LABEL.get(top["signal"], top["signal"])
        parts.append(f"。失注の主因は「{label}」（{top['count']}件）")
    if st["recommended_principle_ids"]:
        parts.append(f"。推奨原則: {'、'.join(st['recommended_principle_ids'])}")
    return "".join(parts) + "。"


def _report(level: str, category: str, industry: str,
            deals: list[dict], st: dict) -> dict:
    ident = f"cat={category}|ind={industry}" if level == "leaf" else f"cat={category}"
    return {
        "id": ident,
        "level": level,
        "category": category,
        "industry": industry,
        "deal_ids": sorted(d["deal_id"] for d in deals),
        **st,
        "narrative_ja": _narrative(category, industry, st),
        "narrative_source": "template",
        "grounded": True,
    }


def build_reports(today: date | None = None) -> list[dict]:
    """Partition all deals into category rollups + (thick) category×industry leaves,
    each with deterministic stats and a templated narrative. GPU-free."""
    today = today or config.today()
    by_leaf: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for d in store.all_deals():
        cat = (d.get("product_category") or "").strip() or "未分類"
        cust = store.get_customer(d.get("customer_id", "")) or {}
        ind = (cust.get("industry") or "").strip() or "不明"
        by_leaf[(cat, ind)].append(d)
        by_cat[cat].append(d)

    reports: list[dict] = []
    # Category rollups always exist — they are the fallback home for thin leaves.
    for cat, deals in by_cat.items():
        reports.append(_report("category", cat, "", deals, segment_stats(deals, today)))
    # Leaves only when they carry enough closed deals to say something honest.
    for (cat, ind), deals in by_leaf.items():
        closed = sum(1 for d in deals if _outcome(d.get("order_rank")) in ("won", "lost"))
        if closed < config.SEGMENT_MIN_DEALS:
            continue
        reports.append(_report("leaf", cat, ind, deals, segment_stats(deals, today)))

    reports.sort(key=lambda r: (r["level"] != "category", -r["n_deals"]))
    return reports


# ---------------------------------------------------------------------------
# Runtime loading (committed artifact preferred) + selection.
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_reports() -> tuple[dict, ...]:
    """Committed community reports if built, else a deterministic in-memory build.
    Tuple return so the lru_cache result is safely shared (callers must not mutate)."""
    path = config.COMMUNITIES_PATH
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return tuple(data)
        except (OSError, ValueError):
            pass
    return tuple(build_reports())


def reload() -> None:
    """Drop cached reports (tests / after a rebuild or seed regeneration)."""
    load_reports.cache_clear()


def _mentions(report: dict, text: str) -> bool:
    cat, ind = report.get("category") or "", report.get("industry") or ""
    return bool((cat and cat in text) or (ind and ind in text))


def select(query: str = "", category: str = "", industry: str = "",
           outcome: str = "all", limit: int = 6) -> list[dict]:
    """Pick the community reports relevant to a thematic manager question.

    Explicit `category`/`industry` filter directly. Otherwise we narrow by segment
    names named in `query`; a genuinely broad question (no segment named) falls back
    to CATEGORY rollups only, so the returned context stays bounded (the hierarchy
    paying off). `outcome` only nudges ranking — a report already covers all
    outcomes. Results are ranked to surface where the losing happens."""
    reports = list(load_reports())
    q = query or ""

    def _match(r: dict) -> bool:
        if category and category not in (r.get("category") or ""):
            return False
        if industry:
            if r.get("level") != "leaf":
                return False
            if industry not in (r.get("industry") or ""):
                return False
        return True

    hits = [r for r in reports if _match(r)]

    if not category and not industry:
        named = [r for r in hits if _mentions(r, q)]
        if named:
            hits = named
        else:
            # Broad, un-anchored question → category-level rollups only.
            hits = [r for r in hits if r.get("level") == "category"]

    # Surface where we lose most; break ties by segment size.
    hits.sort(key=lambda r: (-(r.get("n_lost") or 0), -(r.get("n_deals") or 0)))
    return hits[: max(1, int(limit))]


def format_report(r: dict) -> str:
    """Compact grounded string for the tool result: header stats + narrative + the
    dominant failure modes + recommended principle + CITED evidence deal ids."""
    if r.get("level") == "leaf":
        scope = f"{r['category']}×{r['industry']}"
    else:
        scope = f"{r['category']}（カテゴリ全体）"
    head = f"■ {scope} — 案件{r['n_deals']}件"
    if r.get("win_rate") is not None:
        head += (f"／成約{r['n_won']}・失注{r['n_lost']}・進行中{r['n_open']}"
                 f"／勝率{round(r['win_rate'] * 100)}%")
    lines = [head, r.get("narrative_ja", "")]
    if r.get("top_failure_signals"):
        fs = "、".join(f"{SIGNAL_LABEL.get(f['signal'], f['signal'])}({f['count']}件)"
                      for f in r["top_failure_signals"])
        lines.append(f"失注の主な要因: {fs}")
    if r.get("recommended_principle_ids"):
        lines.append(f"推奨原則: {'、'.join(r['recommended_principle_ids'])}")
    if r.get("deal_ids"):
        lines.append(f"根拠案件: {', '.join(r['deal_ids'][:8])}")
    return "\n".join(x for x in lines if x)


# ---------------------------------------------------------------------------
# Grounding gate — every number in a narrative must exist in the stats.
# ---------------------------------------------------------------------------
def allowed_numbers(report: dict) -> set[str]:
    """The set of numeric strings a narrative is allowed to contain: the counts, the
    win-rate percentage, the signal/flag tallies, and the digits inside recommended
    principle ids (e.g. 'P003' → '003')."""
    nums: set[str] = set()
    for k in ("n_deals", "n_won", "n_lost", "n_open"):
        if report.get(k) is not None:
            nums.add(str(report[k]))
    if report.get("win_rate") is not None:
        nums.add(str(round(report["win_rate"] * 100)))
    for f in report.get("top_failure_signals", []):
        nums.add(str(f["count"]))
    for f in report.get("top_flags", []):
        nums.add(str(f["count"]))
    for pid in report.get("recommended_principle_ids", []):
        nums.update(_NUM.findall(pid))
    return nums


def ungrounded_numbers(text: str, report: dict) -> list[str]:
    """Numeric tokens in `text` that are NOT backed by the report's stats — a hard
    hallucination signal used to reject an LLM narrative (mirrors knowledge.generate's
    `_INVENTED` pre-screen)."""
    allowed = allowed_numbers(report)
    return [m for m in _NUM.findall(text or "") if m not in allowed]


if __name__ == "__main__":
    for rep in build_reports():
        print(format_report(rep))
        print("-" * 60)
