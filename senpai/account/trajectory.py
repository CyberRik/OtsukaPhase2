"""Relationship-trajectory detection — deterministic pattern matchers over an
account's aggregates. Each detector returns a Pattern with human-readable
evidence and a polarity (positive | risk | neutral) so the summary and the
account commentary can speak about the relationship's *direction*, not just its
current state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from senpai import config
from senpai.data import store
from senpai.health.scoring import score_deal

from senpai.account.expansion import expansion_opportunities


@dataclass
class Pattern:
    id: str
    label_ja: str
    label_en: str
    evidence: str
    polarity: str   # positive | risk | neutral

    def to_dict(self) -> dict:
        return asdict(self)


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except (ValueError, TypeError):
        return None


def relationship_trajectory(customer_id: str, today: date | None = None) -> list[Pattern]:
    today = today or config.today()
    deals = store.deals_for_customer(customer_id)
    open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
    orders = store.orders_for_customer(customer_id)
    acts = store.activities_for_customer(customer_id)
    act_dates = [dt for dt in (_parse(a.get("activity_date")) for a in acts) if dt]
    order_dates = [dt for dt in (_parse(o.get("ordered_at")) for o in orders) if dt]

    recent_act = sum(1 for dt in act_dates if (today - dt).days < 90)
    prior_act = sum(1 for dt in act_dates if 90 <= (today - dt).days < 180)

    def rev(lo: int, hi: int) -> int:
        return sum(o.get("total_sales_amount", 0) or 0 for o in orders
                   if order_dates and lo <= (today - (_parse(o.get("ordered_at")) or today)).days < hi)

    out: list[Pattern] = []

    # Repeat purchasing — loyalty signal
    months = {dt.strftime("%Y-%m") for dt in order_dates}
    if len(orders) >= 2 and len(months) >= 2:
        out.append(Pattern("repeat_purchasing", "リピート購入", "Repeat purchasing",
                           f"受注{len(orders)}件・{len(months)}か月にわたり購入", "positive"))

    # Activity increasing / declining
    if prior_act > 0 and recent_act >= 1.3 * prior_act:
        out.append(Pattern("activity_increasing", "活動が活発化", "Activity increasing",
                           f"活動 直近90日{recent_act}件 / 前90日{prior_act}件", "positive"))
    elif prior_act >= 3 and recent_act < 0.5 * prior_act:
        out.append(Pattern("activity_declining", "活動が減速", "Activity declining",
                           f"活動 直近90日{recent_act}件 / 前90日{prior_act}件", "risk"))

    # Spend declining
    recent_rev, prior_rev = rev(0, 180), rev(180, 360)
    if prior_rev > 0 and recent_rev < 0.6 * prior_rev:
        out.append(Pattern("spend_declining", "支出が減少", "Spend declining",
                           f"受注額 直近180日¥{recent_rev:,} / 前180日¥{prior_rev:,}", "risk"))

    # Multiple deals stalled
    stalled = [d for d in open_deals
               if score_deal(d, store.activities_for_deal(d["deal_id"]), today=today).band == "red"]
    if len(stalled) >= 2:
        out.append(Pattern("multiple_stalled", "複数案件が停滞", "Multiple deals stalled",
                           f"赤判定の進行中案件 {len(stalled)}件: "
                           + "、".join(d["deal_id"] for d in stalled), "risk"))

    # Strong engagement but weak progression
    advanced = sum(1 for d in open_deals
                   if config.rank_num(d.get("order_rank"))
                   < config.rank_num(d.get("initial_order_rank") or d.get("order_rank")))
    if recent_act >= 4 and advanced == 0 and recent_rev == 0 and open_deals:
        out.append(Pattern("engaged_no_progress", "接触は多いが前進なし",
                           "Strong engagement, weak progression",
                           f"直近90日{recent_act}件接触も、前進案件0・受注0", "risk"))

    # Loyal but dormant
    won = sum(1 for d in deals if d.get("order_rank") in config.WON_RANKS)
    last_act_days = (today - max(act_dates)).days if act_dates else None
    if won >= 2 and last_act_days is not None and last_act_days >= 60:
        out.append(Pattern("loyal_dormant", "実績ある常連だが休眠", "Loyal but dormant",
                           f"過去成約{won}件だが最終活動{last_act_days}日前", "risk"))

    # Expansion potential (links to the expansion engine)
    if open_deals and expansion_opportunities(customer_id):
        n = len(expansion_opportunities(customer_id))
        out.append(Pattern("expansion_potential", "拡大余地あり", "Expansion potential",
                           f"未取引/更改カテゴリに{n}件の機会", "positive"))

    return out
