"""Rep coaching profile — the page a manager opens before a 1:1.

Aggregates the deterministic coaching issues (senpai.coaching.compute_issues)
across a rep's whole open book into their **recurring** weaknesses, ranked, each
grounded in real deals and tied to a validated interview-cited principle
(senpai.knowledge), a real past case (senpai.coach.cases), and one concrete
development action. Also surfaces the rep's strengths, a headline development
focus, 1:1 talking points, and the status of their open coaching threads.

No new scores or predictions — every number maps to a rule a manager can read off
the data, exactly like the manager Coaching Workspace it complements.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from senpai import config
from senpai.coach.cases import find_similar_cases
from senpai.coach.explainability import explain_coaching_issue
from senpai.coaching import ISSUE_PRIORITY, compute_issues
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import _has_decision_maker, score_deal
from senpai.knowledge import store as kstore

# Per-issue grounding: the validated principle(s) it teaches, a retrieval cue for a
# representative past case, and one concrete development action (Japanese).
_ISSUE_META: dict[str, dict] = {
    "missing_decision_maker": {
        "principles": ["P003", "P006"], "cue": "決裁者 部長 キーマン 意思決定",
        "action": "強いランクの案件ほど、現場担当に『最終決定はどなたと進めますか』と決裁ルートを早期に確認する。"},
    "long_inactivity": {
        "principles": ["P001"], "cue": "検討します 先送り 連絡 停滞",
        "action": "停滞した案件はその場で次回接触日を仮押さえし、案件を宙に浮かせない。"},
    "weak_customer_discovery": {
        "principles": ["P008", "P010"], "cue": "課題 ヒアリング 初回 環境",
        "action": "提案の前に顧客課題を日報に必ず残し、課題ベースで提案軸を組み立てる。"},
    "premature_discount": {
        "principles": ["P002"], "cue": "値引き 価格 コスト",
        "action": "価値が固まる前に値引きを切らない。台数増やオプションとセットで条件を返す。"},
    "repeated_unresolved": {
        "principles": ["P001"], "cue": "検討 保留 ランク低下",
        "action": "ランク低下の根本原因を一つ特定し、次アクションで確実に前進させる。"},
    "confidence_mismatch": {
        "principles": ["P003"], "cue": "決裁 上と相談",
        "action": "強気のランクは、見積・決裁者接触・直近活動など観測事実の裏づけを取ってから維持する。"},
    "incomplete_reports": {
        "principles": [], "cue": "日報 記録",   # a data-hygiene flag, not a sales principle
        "action": "必須項目(決裁者・顧客課題・次アクション)を日報に必ず埋める習慣をつける。"},
}

# Severity ordering so the headline weakness is the most *important* recurring issue,
# not merely the most frequent (e.g. a missing decision-maker outranks report hygiene).
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

# Human-facing issue labels (Japanese), reused for talking points.
_ISSUE_LABEL: dict[str, str] = {
    "confidence_mismatch": "自信と実態の乖離",
    "missing_decision_maker": "決裁者の未特定",
    "long_inactivity": "長期の活動停滞",
    "premature_discount": "早すぎる値引き",
    "repeated_unresolved": "停滞の繰り返し(ランク低下)",
    "weak_customer_discovery": "顧客課題のヒアリング不足",
    "incomplete_reports": "日報の記入漏れ",
}


def _principle_brief(issue: str) -> dict | None:
    """The best available validated principle for an issue (approved preferred)."""
    ids = _ISSUE_META.get(issue, {}).get("principles", [])
    best = None
    for pid in ids:
        p = kstore.get_principle(pid)
        if not p:
            continue
        if getattr(p, "status", "") == "approved":           # prefer approved
            return {"id": p.principle_id, "statement": p.statement, "approved": True}
        if best is None:
            best = {"id": p.principle_id, "statement": p.statement, "approved": False}
    return best


def _case_brief(issue: str, deal: dict | None, today: date) -> dict | None:
    """A representative real past case (win/loss) that teaches this issue."""
    cue = _ISSUE_META.get(issue, {}).get("cue", "")
    cases = find_similar_cases(cue, deal=deal, max_n=2, today=today)
    if not cases:
        return None
    c = cases[0]
    return {"deal_id": c["deal_id"], "customer": c["customer"],
            "outcome": c["outcome"], "product_category": c.get("product_category", ""),
            "principle_ids": c.get("principle_ids", [])}


def rep_coaching_profile(employee_id: str, today: date | None = None) -> dict:
    """Aggregate a rep's recurring coaching weaknesses across their open book,
    grounded in real deals + a validated principle + a real case + an action."""
    today = today or config.today()
    rep = store.get_rep(employee_id)
    deals = [d for d in store.deals_for_rep(employee_id)
             if config.is_open_rank(d.get("order_rank"))]

    issue_counter: Counter = Counter()
    issue_deals: dict[str, list[str]] = {}
    bands = {"red": 0, "yellow": 0, "green": 0}
    risk_sum = 0
    dm_strong_total = dm_strong_hit = 0       # decision-maker rate on strong ranks
    challenge_total = challenge_filled = 0
    for d in deals:
        acts = store.activities_for_deal(d["deal_id"])
        res = score_deal(d, acts, today=today)
        flags = deal_flags(d, acts, health_band=res.band, today=today)
        bands[res.band] += 1
        risk_sum += res.score
        for it in compute_issues(d, acts, res, flags, today):
            issue_counter[it["issue"]] += 1
            issue_deals.setdefault(it["issue"], []).append(d["deal_id"])
        if d.get("order_rank") in config.DECISION_MAKER_RANKS:
            dm_strong_total += 1
            dm_strong_hit += 1 if _has_decision_maker(acts) else 0
        challenge_total += len(acts)
        challenge_filled += sum(1 for a in acts if a.get("customer_challenge"))

    n = len(deals)
    weaknesses = []
    # Rank by severity first, then frequency, so the focus is the most important
    # recurring issue (a missing decision-maker outranks report hygiene).
    ordered = sorted(issue_counter.items(),
                     key=lambda kv: (_PRIORITY_RANK.get(ISSUE_PRIORITY.get(kv[0], "low"), 2),
                                     -kv[1]))
    for issue, count in ordered:
        ex_deals = issue_deals.get(issue, [])
        rep_deal = store.get_deal(ex_deals[0]) if ex_deals else None
        weaknesses.append({
            "issue": issue, "label": _ISSUE_LABEL.get(issue, issue),
            "count": count, "share": round(count / n, 2) if n else 0.0,
            "example_deals": ex_deals[:5],
            "principle": _principle_brief(issue),
            "case": _case_brief(issue, rep_deal, today),
            "action": _ISSUE_META.get(issue, {}).get("action", ""),
        })

    # Headline development focus + its explainability card (on a representative deal).
    focus = weaknesses[0] if weaknesses else None
    focus_explanation = None
    if focus and focus["example_deals"]:
        d0 = store.get_deal(focus["example_deals"][0])
        if d0:
            exp = explain_coaching_issue(
                issue_key=focus["issue"], params={}, deal=d0,
                activities=store.activities_for_deal(d0["deal_id"]), today=today)
            focus_explanation = exp.to_dict()

    strengths = _strengths(issue_counter, dm_strong_total, dm_strong_hit,
                           challenge_total, challenge_filled, bands, n)

    # Coaching threads — the acted-on signal (resolved = coaching landed).
    threads = store.coaching_threads_for_rep(employee_id)
    resolved = sum(1 for t in threads if t.get("status") == "resolved")
    thread_summary = {
        "total": len(threads), "open": sum(1 for t in threads if t.get("status") == "open"),
        "acknowledged": sum(1 for t in threads if t.get("status") == "acknowledged"),
        "resolved": resolved,
        "acted_on_rate": round(resolved / len(threads), 2) if threads else None,
    }

    return {
        "employee_id": employee_id,
        "name": rep.get("name") if rep else employee_id,
        "role": rep.get("role") if rep else "",
        "open_deals": n,
        "at_risk": bands["red"] + bands["yellow"],
        "avg_risk": round(risk_sum / n) if n else 0,
        "band_mix": bands,
        "development_focus": focus["issue"] if focus else None,
        "focus_explanation": focus_explanation,
        "weaknesses": weaknesses,
        "strengths": strengths,
        "talking_points": _talking_points(rep, focus, strengths, thread_summary),
        "threads": thread_summary,
    }


def _strengths(issue_counter, dm_total, dm_hit, ch_total, ch_filled, bands, n) -> list[str]:
    out: list[str] = []
    if dm_total >= 3 and dm_hit / dm_total >= 0.7:
        out.append("強いランクの案件で決裁者を早期に特定できている")
    if ch_total and ch_filled / ch_total >= 0.85:
        out.append("顧客課題のヒアリングを日報に丁寧に残せている")
    if "premature_discount" not in issue_counter:
        out.append("値引きに頼らず価値で提案できている")
    if n and bands["green"] / n >= 0.5:
        out.append("担当案件の健全度を高く保てている")
    return out


def _talking_points(rep, focus, strengths, threads) -> list[str]:
    name = rep.get("name") if rep else "本担当"
    pts: list[str] = []
    if strengths:
        pts.append(f"まず強みを認める: {strengths[0]}。")
    if focus:
        pts.append(f"重点育成テーマは『{focus['label']}』。例: {', '.join(focus['example_deals'][:3])}。"
                   f"次の一手: {focus['action']}")
        if focus.get("case"):
            c = focus["case"]
            pts.append(f"実例で学ぶ: 過去案件 {c['deal_id']}({c['customer']}・"
                       f"{'受注' if c['outcome'] == 'won' else '失注'})を一緒に振り返る。")
    if threads["total"]:
        if threads["acted_on_rate"] is not None and threads["acted_on_rate"] >= 0.5:
            pts.append("過去のコーチングには概ね対応できている。継続を後押しする。")
        else:
            pts.append(f"未対応のコーチング指摘が残っている(解決 {threads['resolved']}/{threads['total']})。フォローする。")
    return pts


def team_coaching_profiles(today: date | None = None,
                           rep_ids: set[str] | None = None) -> list[dict]:
    """One compact profile per rep with open deals, ranked so the reps who need
    the most coaching attention come first (mirrors tools.rep_coaching_focus).

    `rep_ids`, when given, limits the rollup to those reps — a manager's own
    coachees (see store.coachees_of). None = the whole team (default)."""
    today = today or config.today()
    rows = []
    for rep in store.all_reps():
        if rep_ids is not None and rep["employee_id"] not in rep_ids:
            continue
        prof = rep_coaching_profile(rep["employee_id"], today=today)
        if not prof["open_deals"]:
            continue
        rows.append({
            "employee_id": prof["employee_id"], "name": prof["name"], "role": prof["role"],
            "open_deals": prof["open_deals"], "at_risk": prof["at_risk"],
            "avg_risk": prof["avg_risk"], "development_focus": prof["development_focus"],
            "n_weaknesses": len(prof["weaknesses"]),
            "acted_on_rate": prof["threads"]["acted_on_rate"],
        })
    rows.sort(key=lambda r: (r["at_risk"], r["avg_risk"]), reverse=True)
    return rows
