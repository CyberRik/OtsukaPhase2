"""Coaching Explainability — Why did Senpai recommend this?

For every coaching recommendation (lens, signal, flag, coaching issue), this
module assembles a grounded explanation:

  1. Trigger Conditions — which rule fired and what data matched it
  2. Supporting Evidence — the actual field values behind the trigger
  3. Similar Historical Cases — real closed deals with the same pattern
  4. Outcome Statistics — win/loss rates computed from real data only

Hard grounding rule: every statistic comes from ``store.all_deals()``. When
fewer than ``MIN_SAMPLE`` closed deals match a condition set, outcome stats
are returned as ``None`` — never interpolated or invented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from senpai import config
from senpai.coach.cases import (
    THEME_PRINCIPLES,
    _has_decision_maker,
    _was_discounted,
    find_similar_cases,
)
from senpai.data import store
from senpai.health.flags import Flag, deal_flags
from senpai.health.scoring import Signal, _d, score_deal
from senpai.knowledge import store as kstore

# Minimum closed deals for a condition set before we report outcome statistics.
# Below this threshold we say "insufficient data" rather than misleading %.
MIN_SAMPLE = 5


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class TriggerCondition:
    """One rule that fired and why."""
    rule_id: str          # e.g. "lens:decision_maker", "signal:staleness"
    rule_type: str        # "lens" | "signal" | "flag" | "issue" | "presence"
    description: str      # human-readable reason the rule fired
    description_en: str   # English version
    matched_data: dict = field(default_factory=dict)  # actual field values

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceItem:
    """One piece of grounded evidence from the deal record."""
    field: str            # SPR field name
    value: str            # actual value
    interpretation: str   # what it means for this recommendation
    interpretation_en: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SimilarCase:
    """A real closed deal that illustrates the same pattern."""
    deal_id: str
    customer: str
    outcome: str          # "won" | "lost"
    relevance: str        # why this case is similar
    relevance_en: str
    principle_ids: list[str] = field(default_factory=list)
    lesson: str = ""      # principle statement

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OutcomeStats:
    """Win/loss rates from real closed deals matching similar conditions."""
    total_similar: int
    won: int
    lost: int
    loss_rate: float           # lost / (won + lost), 0-1
    conditions_desc: str       # what "similar" means here
    conditions_desc_en: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Explanation:
    """Full explainability package for one coaching recommendation."""
    recommendation_id: str
    recommendation_text: str
    triggers: list[TriggerCondition] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    similar_cases: list[SimilarCase] = field(default_factory=list)
    outcome_stats: OutcomeStats | None = None
    confidence: str = "medium"         # "high" | "medium" | "low"
    principle_id: str | None = None
    principle_statement: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["triggers"] = [t.to_dict() for t in self.triggers]
        d["evidence"] = [e.to_dict() for e in self.evidence]
        d["similar_cases"] = [c.to_dict() for c in self.similar_cases]
        d["outcome_stats"] = self.outcome_stats.to_dict() if self.outcome_stats else None
        return d


# ---------------------------------------------------------------------------
# Outcome statistics — computed from real data only
# ---------------------------------------------------------------------------
def _closed_deals() -> list[dict]:
    """All closed deals (won + lost), cached per call chain."""
    return [d for d in store.all_deals()
            if d.get("order_rank") in config.WON_RANKS | config.DEAD_RANKS]


def _outcome(rank: str | None) -> str | None:
    if rank in config.WON_RANKS:
        return "won"
    if rank in config.DEAD_RANKS:
        return "lost"
    return None


def compute_outcome_stats(
    condition_fn,
    conditions_desc: str,
    conditions_desc_en: str,
) -> OutcomeStats | None:
    """Count won/lost among closed deals matching ``condition_fn(deal, acts)``.

    Returns None when fewer than MIN_SAMPLE deals match — we never show
    percentages from tiny samples.
    """
    won, lost = 0, 0
    for d in _closed_deals():
        acts = store.activities_for_deal(d["deal_id"])
        if not condition_fn(d, acts):
            continue
        out = _outcome(d.get("order_rank"))
        if out == "won":
            won += 1
        elif out == "lost":
            lost += 1
    total = won + lost
    if total < MIN_SAMPLE:
        return None
    return OutcomeStats(
        total_similar=total,
        won=won,
        lost=lost,
        loss_rate=round(lost / total, 2) if total else 0,
        conditions_desc=conditions_desc,
        conditions_desc_en=conditions_desc_en,
    )


# ---------------------------------------------------------------------------
# Similar-case assembly with lesson text
# ---------------------------------------------------------------------------
def _build_similar_cases(note: str, deal: dict | None,
                         theme_filter: str | None = None,
                         today: date | None = None) -> list[SimilarCase]:
    """Retrieve similar past cases and enrich with lesson text."""
    raw = find_similar_cases(note, deal=deal, max_n=3, today=today)
    cases: list[SimilarCase] = []
    for c in raw:
        # Only include cases matching the theme if a filter is specified
        if theme_filter and c.get("theme") != theme_filter:
            continue

        lessons = []
        for pid in c.get("principle_ids", []):
            p = kstore.get_principle(pid)
            if p:
                lessons.append(f"{pid}: {p.statement}")

        dm_text = "DM identified" if c.get("decision_maker") else "No DM identified"
        disc_text = "discounted" if c.get("discounted") else "no discount"
        rel_parts = [dm_text, disc_text, f"{c.get('n_activities', 0)} activities"]
        relevance = "、".join(rel_parts)
        relevance_en = ", ".join(rel_parts)

        cases.append(SimilarCase(
            deal_id=c["deal_id"],
            customer=c.get("customer", c["deal_id"]),
            outcome=c.get("outcome", "lost"),
            relevance=relevance,
            relevance_en=relevance_en,
            principle_ids=c.get("principle_ids", []),
            lesson="; ".join(lessons) if lessons else "",
        ))
    return cases


# ---------------------------------------------------------------------------
# Lens explanations
# ---------------------------------------------------------------------------
def explain_lens(
    lens_name: str,
    lens_cues: list[str],
    lens_tags: list[str],
    observation: str,
    note: str,
    deal: dict | None,
    activities: list[dict] | None,
    today: date | None = None,
) -> Explanation:
    """Build an explanation for a lens that fired (cues absent from note)."""
    today = today or config.today()
    activities = activities or []

    # -- Trigger --
    trigger = TriggerCondition(
        rule_id=f"lens:{lens_name}",
        rule_type="lens",
        description=f"メモに以下のキーワードが含まれていません: {', '.join(lens_cues[:5])}",
        description_en=f"Note contains none of the expected cues: {', '.join(lens_cues[:5])}",
        matched_data={"absent_cues": lens_cues, "lens": lens_name},
    )

    # -- Evidence from deal --
    evidence: list[EvidenceItem] = []
    if deal:
        if lens_name == "decision_maker":
            dm = _has_decision_maker(activities)
            n_acts = len(activities)
            dm_acts = sum(1 for a in activities
                         if any(t in (a.get("business_card_info") or "")
                                for t in config.DECISION_MAKER_TITLES))
            evidence.append(EvidenceItem(
                field="business_card_info",
                value=f"{dm_acts}/{n_acts} activities have DM-titled contacts",
                interpretation="決裁者との接触が記録されていません" if not dm
                               else "決裁者との接触は記録済み",
                interpretation_en=f"{'No' if not dm else ''} decision-maker contact recorded "
                                  f"across {n_acts} activities",
            ))
            rank = deal.get("order_rank")
            if rank in config.DECISION_MAKER_RANKS:
                evidence.append(EvidenceItem(
                    field="order_rank",
                    value=rank or "-",
                    interpretation=f"ランク{rank}では決裁者の特定が期待されます",
                    interpretation_en=f"At rank {rank}, a decision-maker should be identified",
                ))

        elif lens_name == "timeline":
            last_act = next((a.get("activity_date") for a in activities
                            if a.get("activity_date")), None)
            if last_act:
                days = (_d(last_act) and (today - _d(last_act)).days) or 0
                evidence.append(EvidenceItem(
                    field="activity_date",
                    value=f"Last activity: {last_act} ({days} days ago)",
                    interpretation=f"直近の活動から{days}日が経過",
                    interpretation_en=f"{days} days since last activity",
                ))
            eod = deal.get("expected_order_date")
            if eod:
                evidence.append(EvidenceItem(
                    field="expected_order_date",
                    value=eod,
                    interpretation=f"完了予定日: {eod}",
                    interpretation_en=f"Expected order date: {eod}",
                ))

        elif lens_name == "budget":
            q = store.quote_for_deal(deal["deal_id"])
            if q:
                evidence.append(EvidenceItem(
                    field="quote_amount",
                    value=f"¥{int(q.get('quote_amount', 0) or 0):,}",
                    interpretation="見積は提出済みだが予算確認の記載がありません",
                    interpretation_en="Quote issued but no budget confirmation noted",
                ))

        elif lens_name == "criteria":
            evidence.append(EvidenceItem(
                field="daily_report",
                value=f"{sum(1 for a in activities if a.get('daily_report'))}/{len(activities)} reports filed",
                interpretation="日報に判断基準に関する記載がありません",
                interpretation_en="No mention of decision criteria in daily reports",
            ))

        elif lens_name == "next_step":
            evidence.append(EvidenceItem(
                field="daily_report",
                value="Latest: " + ((activities[0].get("daily_report") or "")[:60] + "…"
                                    if activities else "No activities"),
                interpretation="次の具体的なアクションが決まっていません",
                interpretation_en="No concrete next step recorded",
            ))

    # -- Similar cases --
    theme_map = {
        "decision_maker": "no_decision_maker",
        "timeline": "stalled",
        "budget": "budget",
        "criteria": "discovery",
        "next_step": "stalled",
    }
    theme = theme_map.get(lens_name)
    similar = _build_similar_cases(note, deal, theme_filter=None, today=today)

    # -- Outcome stats --
    if lens_name == "decision_maker":
        stats = compute_outcome_stats(
            lambda d, acts: not _has_decision_maker(acts)
                           and d.get("order_rank") not in (config.WON_RANKS | config.DEAD_RANKS | {None}),
            conditions_desc="決裁者が未特定のまま進んだ案件",
            conditions_desc_en="Deals that proceeded without identifying a decision-maker",
        )
    elif lens_name == "timeline":
        stats = compute_outcome_stats(
            lambda d, acts: (len(acts) > 0
                            and _d(acts[0].get("activity_date")) is not None
                            and (today - _d(acts[0].get("activity_date"))).days > 30),
            conditions_desc="30日以上接触がなかった案件",
            conditions_desc_en="Deals with > 30 days without contact",
        )
    elif lens_name == "budget":
        stats = compute_outcome_stats(
            lambda d, acts: not any("予算" in (a.get("daily_report") or "")
                                   for a in acts),
            conditions_desc="日報に予算の記載がなかった案件",
            conditions_desc_en="Deals with no budget mention in daily reports",
        )
    else:
        stats = None

    # -- Principle linkage --
    principle_ids = THEME_PRINCIPLES.get(theme, [])
    pid = principle_ids[0] if principle_ids else None
    p = kstore.get_principle(pid) if pid else None
    confidence = "high" if p and len(p.interview_ids) >= 2 else "medium" if p else "low"

    return Explanation(
        recommendation_id=f"lens:{lens_name}",
        recommendation_text=observation,
        triggers=[trigger],
        evidence=evidence,
        similar_cases=similar[:3],
        outcome_stats=stats,
        confidence=confidence,
        principle_id=pid,
        principle_statement=p.statement if p else None,
    )


# ---------------------------------------------------------------------------
# Signal explanations
# ---------------------------------------------------------------------------
_SIGNAL_EVIDENCE: dict[str, str] = {
    "staleness": "activity_date",
    "rank_age": "rank_updated_at",
    "order_date_past": "expected_order_date",
    "rank_regression": "order_rank / initial_order_rank",
    "missing_dm": "business_card_info",
    "stall_language": "daily_report",
    "low_activity": "activity_date",
}

_SIGNAL_CONDITION_JA: dict[str, str] = {
    "staleness": "接触間隔がランク別基準を超えた案件",
    "rank_age": "ランク滞留がベンチマークを超えた案件",
    "order_date_past": "完了予定日を過ぎた案件",
    "rank_regression": "ランクが初期より低下した案件",
    "missing_dm": "強いランクで決裁者が未特定の案件",
    "stall_language": "直近日報に停滞サインがあった案件",
    "low_activity": "直近30日の活動が0件の案件",
}

_SIGNAL_CONDITION_EN: dict[str, str] = {
    "staleness": "Deals where contact gap exceeded rank benchmark",
    "rank_age": "Deals stuck at rank beyond benchmark days",
    "order_date_past": "Deals past expected order date",
    "rank_regression": "Deals where rank dropped from initial",
    "missing_dm": "Deals at strong rank without identified decision-maker",
    "stall_language": "Deals with stall language in latest daily report",
    "low_activity": "Deals with zero activity in the last 30 days",
}


def explain_signal(
    signal: Signal,
    deal: dict,
    activities: list[dict],
    note: str = "",
    today: date | None = None,
) -> Explanation:
    """Build an explanation for a health signal that fired."""
    today = today or config.today()
    rank = deal.get("order_rank")

    trigger = TriggerCondition(
        rule_id=f"signal:{signal.name}",
        rule_type="signal",
        description=signal.reason,
        description_en=signal.reason,  # already has signal detail
        matched_data={"signal": signal.name, "points": signal.points},
    )

    evidence: list[EvidenceItem] = []
    src_field = _SIGNAL_EVIDENCE.get(signal.name, "")

    if signal.name == "staleness":
        act_dates = sorted((_d(a.get("activity_date")) for a in activities
                           if _d(a.get("activity_date"))), reverse=True)
        last = act_dates[0] if act_dates else None
        if last:
            days = (today - last).days
            _, cadence = config.RANK_BENCHMARKS.get(rank, (45, 14))
            evidence.append(EvidenceItem(
                field="activity_date",
                value=f"Last: {last.isoformat()} ({days}d ago)",
                interpretation=f"ランク{rank}の接触目安{cadence}日に対し{days}日経過",
                interpretation_en=f"{days} days since last contact vs {cadence}-day benchmark for rank {rank}",
            ))

    elif signal.name == "rank_age":
        updated = _d(deal.get("rank_updated_at"))
        if updated:
            in_rank = (today - updated).days
            max_days, _ = config.RANK_BENCHMARKS.get(rank, (45, 14))
            evidence.append(EvidenceItem(
                field="rank_updated_at",
                value=f"{updated.isoformat()} ({in_rank}d at {rank})",
                interpretation=f"ランク{rank}に{in_rank}日滞留 (目安{max_days}日)",
                interpretation_en=f"At rank {rank} for {in_rank} days (benchmark {max_days})",
            ))

    elif signal.name == "missing_dm":
        dm_count = sum(1 for a in activities
                      if any(t in (a.get("business_card_info") or "")
                             for t in config.DECISION_MAKER_TITLES))
        evidence.append(EvidenceItem(
            field="business_card_info",
            value=f"{dm_count}/{len(activities)} activities with DM contact",
            interpretation=f"ランク{rank}では決裁者接触が期待されるが未記録",
            interpretation_en=f"At rank {rank}, DM contact expected but {dm_count} of {len(activities)} activities have it",
        ))

    elif signal.name == "rank_regression":
        init = deal.get("initial_order_rank")
        evidence.append(EvidenceItem(
            field="order_rank",
            value=f"{init} → {rank}",
            interpretation=f"初期ランク{init}から{rank}に低下",
            interpretation_en=f"Rank dropped from {init} to {rank}",
        ))

    elif signal.name == "order_date_past":
        eod = deal.get("expected_order_date")
        evidence.append(EvidenceItem(
            field="expected_order_date",
            value=eod or "-",
            interpretation=f"完了予定日{eod}を過ぎてもオープン",
            interpretation_en=f"Past expected order date {eod}, deal still open",
        ))

    elif signal.name == "stall_language":
        latest = activities[0].get("daily_report", "") if activities else ""
        hit = next((w for w in config.STALL_LEXICON if w in latest), None)
        evidence.append(EvidenceItem(
            field="daily_report",
            value=f'"{hit}" found in latest report' if hit else "Stall phrase detected",
            interpretation=f"停滞サイン「{hit}」が直近の日報に記載",
            interpretation_en=f'Stall phrase "{hit}" found in latest daily report',
        ))

    elif signal.name == "low_activity":
        evidence.append(EvidenceItem(
            field="activity_date",
            value=f"0 activities in last 30 days",
            interpretation="直近30日間に活動記録なし",
            interpretation_en="No activities recorded in the last 30 days",
        ))

    # Outcome stats for this signal type
    cond_ja = _SIGNAL_CONDITION_JA.get(signal.name, "")
    cond_en = _SIGNAL_CONDITION_EN.get(signal.name, "")

    if signal.name == "missing_dm":
        stats = compute_outcome_stats(
            lambda d, acts: not _has_decision_maker(acts),
            cond_ja, cond_en,
        )
    elif signal.name == "staleness":
        stats = compute_outcome_stats(
            lambda d, acts: (len(acts) > 0
                            and _d(acts[0].get("activity_date")) is not None
                            and (today - _d(acts[0].get("activity_date"))).days > 30),
            cond_ja, cond_en,
        )
    elif signal.name == "rank_regression":
        stats = compute_outcome_stats(
            lambda d, acts: (d.get("initial_order_rank")
                            and config.rank_num(d.get("order_rank"))
                            > config.rank_num(d.get("initial_order_rank"))),
            cond_ja, cond_en,
        )
    else:
        stats = None

    similar = _build_similar_cases(note, deal, today=today)

    # Map signal to most relevant principle
    signal_principle_map = {
        "missing_dm": "P006",
        "staleness": "P001",
        "stall_language": "P001",
        "rank_regression": "P001",
    }
    pid = signal_principle_map.get(signal.name)
    p = kstore.get_principle(pid) if pid else None
    confidence = "high" if p and len(p.interview_ids) >= 2 else "medium" if p else "low"

    return Explanation(
        recommendation_id=f"signal:{signal.name}",
        recommendation_text=signal.reason,
        triggers=[trigger],
        evidence=evidence,
        similar_cases=similar[:3],
        outcome_stats=stats,
        confidence=confidence,
        principle_id=pid,
        principle_statement=p.statement if p else None,
    )


# ---------------------------------------------------------------------------
# Coaching issue explanations (manager workspace)
# ---------------------------------------------------------------------------
_ISSUE_PRINCIPLE_MAP: dict[str, str] = {
    "confidence_mismatch": "P001",
    "missing_decision_maker": "P006",
    "long_inactivity": "P001",
    "premature_discount": "P002",
    "repeated_unresolved": "P001",
    "weak_customer_discovery": "P008",
    "incomplete_reports": "P001",
}

_ISSUE_CONDITION_JA: dict[str, str] = {
    "confidence_mismatch": "ランクが強いが健全度が赤の案件",
    "missing_decision_maker": "決裁者が未特定の案件",
    "long_inactivity": "30日以上活動がない案件",
    "premature_discount": "決裁者未特定で10%超の値引きがある案件",
    "repeated_unresolved": "ランクが初期より低下した案件",
    "weak_customer_discovery": "課題ヒアリング率が低い案件",
    "incomplete_reports": "必須項目が未入力の案件",
}

_ISSUE_CONDITION_EN: dict[str, str] = {
    "confidence_mismatch": "Deals with strong rank but red health",
    "missing_decision_maker": "Deals without identified decision-maker",
    "long_inactivity": "Deals with > 30 days without activity",
    "premature_discount": "Deals discounted > 10% without DM identified",
    "repeated_unresolved": "Deals where rank dropped from initial",
    "weak_customer_discovery": "Deals with low customer challenge fill rate",
    "incomplete_reports": "Deals with missing required fields",
}


def explain_coaching_issue(
    issue_key: str,
    params: dict,
    deal: dict,
    activities: list[dict],
    today: date | None = None,
) -> Explanation:
    """Build an explanation for a manager coaching issue."""
    today = today or config.today()

    trigger = TriggerCondition(
        rule_id=f"issue:{issue_key}",
        rule_type="issue",
        description=_ISSUE_CONDITION_JA.get(issue_key, issue_key),
        description_en=_ISSUE_CONDITION_EN.get(issue_key, issue_key),
        matched_data=params,
    )

    evidence: list[EvidenceItem] = []

    if issue_key == "confidence_mismatch":
        rank = params.get("rank", "-")
        evidence.append(EvidenceItem(
            field="order_rank",
            value=rank,
            interpretation=f"ランクは「{rank}」だが健全度は赤",
            interpretation_en=f'Rank is "{rank}" but deal health is red',
        ))

    elif issue_key == "missing_decision_maker":
        reports = params.get("reports", 0)
        evidence.append(EvidenceItem(
            field="business_card_info",
            value=f"{reports} reports filed, 0 with DM contact",
            interpretation="日報に決裁者との接触記録がありません",
            interpretation_en=f"{reports} reports filed but none mention a decision-maker",
        ))

    elif issue_key == "long_inactivity":
        days = params.get("days", 0)
        evidence.append(EvidenceItem(
            field="activity_date",
            value=f"{days} days since last activity",
            interpretation=f"直近の活動から{days}日経過",
            interpretation_en=f"{days} days since last activity",
        ))

    elif issue_key == "premature_discount":
        rate = params.get("rate", 0)
        evidence.append(EvidenceItem(
            field="discount_rate",
            value=f"{rate}%",
            interpretation=f"決裁者未確認のまま{rate}%の値引きを提示",
            interpretation_en=f"{rate}% discount offered before decision-maker confirmed",
        ))

    elif issue_key == "repeated_unresolved":
        init_rank = params.get("init", "-")
        curr_rank = params.get("rank", "-")
        evidence.append(EvidenceItem(
            field="order_rank",
            value=f"{init_rank} → {curr_rank}",
            interpretation=f"初期ランク{init_rank}から{curr_rank}に低下",
            interpretation_en=f"Rank dropped from {init_rank} to {curr_rank}",
        ))

    elif issue_key == "weak_customer_discovery":
        filled = params.get("filled", 0)
        total = params.get("total", 0)
        evidence.append(EvidenceItem(
            field="customer_challenge",
            value=f"{filled}/{total} activities have customer challenges",
            interpretation=f"課題ヒアリング率: {filled}/{total} ({round(filled/total*100) if total else 0}%)",
            interpretation_en=f"Customer challenge fill rate: {filled}/{total}",
        ))

    # Outcome stats
    cond_ja = _ISSUE_CONDITION_JA.get(issue_key, "")
    cond_en = _ISSUE_CONDITION_EN.get(issue_key, "")

    if issue_key == "missing_decision_maker":
        stats = compute_outcome_stats(
            lambda d, acts: not _has_decision_maker(acts),
            cond_ja, cond_en,
        )
    elif issue_key == "premature_discount":
        stats = compute_outcome_stats(
            lambda d, acts: _was_discounted(d["deal_id"]) and not _has_decision_maker(acts),
            cond_ja, cond_en,
        )
    elif issue_key == "long_inactivity":
        stats = compute_outcome_stats(
            lambda d, acts: (len(acts) > 0
                            and _d(acts[0].get("activity_date")) is not None
                            and (today - _d(acts[0].get("activity_date"))).days > 30),
            cond_ja, cond_en,
        )
    elif issue_key == "confidence_mismatch":
        stats = compute_outcome_stats(
            lambda d, acts: (d.get("order_rank") in config.OPTIMISTIC_RANKS
                            and score_deal(d, acts, today=today).band == "red"),
            cond_ja, cond_en,
        )
    elif issue_key == "repeated_unresolved":
        stats = compute_outcome_stats(
            lambda d, acts: (d.get("initial_order_rank")
                            and config.rank_num(d.get("order_rank"))
                            > config.rank_num(d.get("initial_order_rank"))),
            cond_ja, cond_en,
        )
    else:
        stats = None

    # Similar cases
    note_text = deal.get("deal_name", "")
    similar = _build_similar_cases(note_text, deal, today=today)

    # Principle linkage
    pid = _ISSUE_PRINCIPLE_MAP.get(issue_key)
    p = kstore.get_principle(pid) if pid else None
    confidence = "high" if p and len(p.interview_ids) >= 2 else "medium" if p else "low"

    return Explanation(
        recommendation_id=f"issue:{issue_key}:{deal['deal_id']}",
        recommendation_text=_ISSUE_CONDITION_JA.get(issue_key, issue_key),
        triggers=[trigger],
        evidence=evidence,
        similar_cases=similar[:3],
        outcome_stats=stats,
        confidence=confidence,
        principle_id=pid,
        principle_statement=p.statement if p else None,
    )


# ---------------------------------------------------------------------------
# Presence-detector explanations (stall / competitor)
# ---------------------------------------------------------------------------
def explain_presence(
    detector: str,
    matched_word: str,
    note: str,
    deal: dict | None,
    activities: list[dict] | None,
    today: date | None = None,
) -> Explanation:
    """Explain a presence-based detector (stall language, competitor mention)."""
    today = today or config.today()

    if detector == "stall":
        trigger = TriggerCondition(
            rule_id="presence:stall",
            rule_type="presence",
            description=f"停滞を示す言葉「{matched_word}」がメモに含まれています",
            description_en=f'Stall phrase "{matched_word}" found in note',
            matched_data={"word": matched_word, "detector": "stall"},
        )
        pid = "P001"
    else:
        trigger = TriggerCondition(
            rule_id="presence:competitor",
            rule_type="presence",
            description=f"競合の存在を示す言葉「{matched_word}」がメモに含まれています",
            description_en=f'Competitor indicator "{matched_word}" found in note',
            matched_data={"word": matched_word, "detector": "competitor"},
        )
        pid = "P009"

    p = kstore.get_principle(pid) if pid else None
    similar = _build_similar_cases(note, deal, today=today)

    return Explanation(
        recommendation_id=f"presence:{detector}",
        recommendation_text=trigger.description,
        triggers=[trigger],
        evidence=[EvidenceItem(
            field="note_text",
            value=f'"{matched_word}"',
            interpretation=trigger.description,
            interpretation_en=trigger.description_en,
        )],
        similar_cases=similar[:2],
        outcome_stats=None,
        confidence="medium" if p else "low",
        principle_id=pid,
        principle_statement=p.statement if p else None,
    )


# ---------------------------------------------------------------------------
# Master assembly — build all explanations for a coach review
# ---------------------------------------------------------------------------
def build_review_explanations(
    note: str,
    fired_lenses: list[dict],      # [{"name": ..., "cues": ..., "tags": ..., "observation": ...}]
    fired_signals: list[Signal],
    fired_flags: list[Flag],
    stall_hit: str | None,
    comp_hit: str | None,
    deal: dict | None,
    activities: list[dict] | None,
    today: date | None = None,
) -> list[Explanation]:
    """Assemble explanations for every coaching item in a review."""
    today = today or config.today()
    activities = activities or []
    explanations: list[Explanation] = []

    for lens in fired_lenses:
        explanations.append(explain_lens(
            lens_name=lens["name"],
            lens_cues=lens["cues"],
            lens_tags=lens["tags"],
            observation=lens["observation"],
            note=note,
            deal=deal,
            activities=activities,
            today=today,
        ))

    for sig in fired_signals:
        if deal:
            explanations.append(explain_signal(
                signal=sig, deal=deal, activities=activities,
                note=note, today=today,
            ))

    if stall_hit:
        explanations.append(explain_presence(
            "stall", stall_hit, note, deal, activities, today,
        ))

    if comp_hit:
        explanations.append(explain_presence(
            "competitor", comp_hit, note, deal, activities, today,
        ))

    return explanations
