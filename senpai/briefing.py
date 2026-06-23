"""Morning briefing — the rep's prioritized next-best-action worklist.

Sweeps a rep's open deals, scores each with the deterministic health engine,
then ranks them by **urgency × value** and attaches ONE concrete next action per
deal, derived from the dominant risk signal. It also adds a *predictive* cadence
nudge: a deal that is about to breach its rank's contact cadence — but hasn't
gone stale yet — is surfaced before it turns yellow.

Pure Python / CPU and fully explainable: no model invents the action. Every line
comes from the same `score_deal` signals and the `RANK_BENCHMARKS` cadence in
config, so the briefing is as auditable as the scoring engine itself.

    from senpai.briefing import morning_briefing, format_briefing
    print(format_briefing(morning_briefing(rep_id="R12")))
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from senpai import config
from senpai.data import store
from senpai.health.scoring import score_deal

_BAND_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
_DUE_TAG = {"overdue": "【超過】", "today": "【本日】", "soon": "【まもなく】", "": ""}


@dataclass
class ActionItem:
    """One deal's recommended action for today."""
    deal_id: str
    customer: str
    rep_id: str
    band: str           # red | yellow | green
    risk: int           # 0–100 health risk
    priority: float     # urgency × value (sort key, higher = do first)
    amount: int         # deal ¥ value
    action: str         # imperative next step, Japanese
    reason: str         # why it matters now, Japanese
    due: str            # overdue | today | soon | ''


def _parse(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _days_since_last_contact(activities: list[dict], today: date) -> int | None:
    """Days since the most recent logged activity (None if no activity)."""
    dates = sorted((d for a in activities if (d := _parse(a.get("activity_date")))),
                   reverse=True)
    return (today - dates[0]).days if dates else None


def _next_action(deal: dict, res, days_since: int | None,
                 cadence: int) -> tuple[str, str, str]:
    """Pick ONE action from the dominant signal. Returns (action, reason, due).

    Ordered by what a rep should tackle first; the first matching signal wins, so
    the most pressing issue becomes the single recommended next step."""
    rank = deal.get("order_rank")
    names = {s.name for s in res.signals}
    ds = days_since if days_since is not None else "—"

    if "order_date_past" in names:
        return ("受注時期を再確認し、完了予定日を更新する",
                "完了予定日を過ぎても未受注", "overdue")
    if "missing_dm" in names:
        return ("決裁者を特定する(役職者へのアプローチを設定)",
                f"{rank}だが決裁者が未特定", "today")
    if "staleness" in names or "low_activity" in names:
        return ("今日フォローの連絡を入れる",
                f"{ds}日間接触なし(目安{cadence}日)", "today")
    if "stall_language" in names:
        return ("停滞の要因をヒアリングし、次の一手を決める",
                "直近の日報に停滞サイン", "today")
    if "rank_regression" in names:
        return ("ランク低下の原因を確認し、立て直し策を打つ",
                "ランクが低下", "today")
    if "rank_age" in names:
        return ("次アクションを設定して案件を前進させる",
                f"{rank}に長期滞留", "soon")
    # Predictive: approaching the contact cadence though not yet stale.
    if days_since is not None and cadence and days_since >= 0.75 * cadence:
        left = max(cadence - days_since, 0)
        return ("早めに次の接触予定を入れる",
                f"あと{left}日で接触目安({cadence}日)に到達", "soon")
    return ("健全。関係維持のため定期接触を継続", "リスク低(健全)", "")


def _priority(res, days_since: int | None, cadence: int,
              amount: int, max_amount: int) -> float:
    """urgency × value. Urgency is the risk score plus a small predictive bump for
    deals nearing their cadence; value scales it by deal size (×0.8…×1.3) so a big
    deal outranks a small one at equal urgency, without ever burying a red deal."""
    urgency = float(res.score)
    if (days_since is not None and cadence
            and days_since >= 0.75 * cadence
            and res.score < config.YELLOW_THRESHOLD):
        urgency += 10.0   # predictive nudge before it goes yellow
    value_weight = 0.8
    if max_amount > 0:
        value_weight = 0.8 + 0.5 * (amount / max_amount)
    return round(urgency * value_weight, 1)


def morning_briefing(rep_id: str = "", today: date | None = None,
                     limit: int = 10, include_healthy: bool = False) -> list[ActionItem]:
    """Prioritized next-best-action list for a rep (or the whole team if no rep).

    By default only deals that need attention are returned (healthy deals with no
    upcoming-cadence nudge are dropped); pass include_healthy=True to keep them.
    Sorted by priority, highest first."""
    today = today or config.today()
    deals = store.deals_for_rep(rep_id) if rep_id else store.open_deals()
    open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
    max_amount = max((d.get("total_order_amount", 0) for d in open_deals), default=0)

    items: list[ActionItem] = []
    for d in open_deals:
        acts = store.activities_for_deal(d["deal_id"])
        res = score_deal(d, acts, today)
        cadence = config.RANK_BENCHMARKS.get(d.get("order_rank"), (45, 14))[1]
        days_since = _days_since_last_contact(acts, today)
        action, reason, due = _next_action(d, res, days_since, cadence)
        amount = d.get("total_order_amount", 0)
        items.append(ActionItem(
            deal_id=d["deal_id"],
            customer=store.customer_name(d["customer_id"]),
            rep_id=store.deal_rep_id(d),
            band=res.band,
            risk=res.score,
            priority=_priority(res, days_since, cadence, amount, max_amount),
            amount=amount,
            action=action,
            reason=reason,
            due=due,
        ))

    items.sort(key=lambda it: it.priority, reverse=True)
    if not include_healthy:
        items = [it for it in items if it.band != "green" or it.due]
    return items[:limit] if limit else items


def format_briefing(items: list[ActionItem], rep_id: str = "",
                    today: date | None = None) -> str:
    """Render a briefing as the short string the chat/tool surface shows."""
    today = today or config.today()
    scope = f"{store.rep_name(rep_id)} さんの" if rep_id else "チームの"
    if not items:
        return f"☀️ {today.isoformat()} 本日対応が必要な案件はありません。すべて健全です。"
    lines = [f"☀️ {today.isoformat()} {scope}本日の優先アクション(上位{len(items)}件):"]
    for i, it in enumerate(items, 1):
        tag = _DUE_TAG[it.due]
        lines.append(
            f"{i}. {_BAND_EMOJI[it.band]} {it.deal_id} {it.customer} "
            f"(¥{it.amount:,} / {tag}リスク{it.risk})\n"
            f"   → {it.action}({it.reason})"
        )
    return "\n".join(lines)
