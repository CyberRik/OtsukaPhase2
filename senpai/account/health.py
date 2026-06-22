"""Account-level health — a deterministic 0–100 score for a whole customer
relationship, NOT a single deal.

Deal health (senpai.health.scoring) answers "is *this opportunity* on track?".
Account health answers "is *this relationship* healthy and growing?" — a senior
manager's question. It is deliberately HIGHER-IS-BETTER (0 worst … 100 best), the
inverse of the deal risk score, so the two are never confused.

Eight weighted dimensions (weights sum to 100), each a pure function returning
(points, max, reason). Everything is computed from committed store records; no
LLM, no randomness. Band: >=70 green (healthy/strategic), 45–69 yellow (watch),
<45 red (at risk).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from senpai import config
from senpai.data import store

# --- dimension weights (single tuning surface) ------------------------------
W_ACTIVITY_TREND = 15
W_INACTIVITY = 10
W_PROGRESSION = 15
W_WIN_RATE = 15
W_QUOTE_ENGAGEMENT = 10
W_ORDER_RECENCY = 15
W_DM_ACCESS = 10
W_GROWTH = 10


@dataclass
class Dimension:
    name: str
    points: float
    max: float
    reason: str


@dataclass
class AccountHealth:
    score: int
    band: str            # green | yellow | red
    dimensions: list[Dimension] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"score": self.score, "band": self.band,
                "dimensions": [asdict(d) for d in self.dimensions]}

    def top_reasons(self, n: int = 3) -> list[str]:
        """The dimensions dragging the score down most (lowest fraction of max)."""
        ranked = sorted(self.dimensions, key=lambda d: d.points / d.max if d.max else 1)
        return [d.reason for d in ranked[:n]]


# --- helpers ----------------------------------------------------------------
def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except (ValueError, TypeError):
        return None


def _days_since(d: str | None, today: date) -> int | None:
    dt = _parse(d)
    return (today - dt).days if dt else None


def _count_between(dates: list[date], today: date, lo: int, hi: int) -> int:
    """How many dates fall in [today-hi, today-lo) days ago."""
    return sum(1 for dt in dates if lo <= (today - dt).days < hi)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# --- the eight dimensions ---------------------------------------------------
def _dim_activity_trend(act_dates: list[date], today: date) -> Dimension:
    recent = _count_between(act_dates, today, 0, 90)
    prior = _count_between(act_dates, today, 90, 180)
    if recent == 0 and prior == 0:
        return Dimension("activity_trend", 0, W_ACTIVITY_TREND, "直近180日の活動なし")
    ratio = recent / prior if prior else 2.0
    pts = _clamp(W_ACTIVITY_TREND * min(1.0, ratio / 1.0), 0, W_ACTIVITY_TREND)
    trend = "増加" if recent > prior else ("横ばい" if recent == prior else "減少")
    return Dimension("activity_trend", round(pts, 1), W_ACTIVITY_TREND,
                     f"活動 直近90日 {recent}件 / 前90日 {prior}件（{trend}）")


def _dim_inactivity(act_dates: list[date], today: date) -> Dimension:
    last = max(act_dates) if act_dates else None
    days = (today - last).days if last else None
    if days is None:
        return Dimension("inactivity", 0, W_INACTIVITY, "活動記録なし")
    pts = _clamp(W_INACTIVITY * (90 - days) / (90 - 14), 0, W_INACTIVITY)
    return Dimension("inactivity", round(pts, 1), W_INACTIVITY,
                     f"最終活動から{days}日")


def _dim_progression(open_deals: list[dict]) -> Dimension:
    # rank_num is lower-is-more-advanced; current < initial means the deal moved
    # forward, current > initial means it slipped back.
    advanced = slipped = 0
    for d in open_deals:
        cur = config.rank_num(d.get("order_rank"))
        ini = config.rank_num(d.get("initial_order_rank") or d.get("order_rank"))
        if cur < ini:
            advanced += 1
        elif cur > ini:
            slipped += 1
    if not open_deals:
        return Dimension("pipeline_progression", W_PROGRESSION / 2, W_PROGRESSION,
                         "進行中の案件なし")
    net = advanced - slipped
    pts = _clamp(W_PROGRESSION / 2 + net * 3, 0, W_PROGRESSION)
    return Dimension("pipeline_progression", round(pts, 1), W_PROGRESSION,
                     f"進行中{len(open_deals)}件: 前進{advanced} / 後退{slipped}")


def _dim_win_rate(deals: list[dict]) -> Dimension:
    won = sum(1 for d in deals if d.get("order_rank") in config.WON_RANKS)
    lost = sum(1 for d in deals if d.get("order_rank") in config.DEAD_RANKS)
    closed = won + lost
    if closed == 0:
        return Dimension("win_rate", W_WIN_RATE / 2, W_WIN_RATE, "成約・失注の実績なし")
    rate = won / closed
    return Dimension("win_rate", round(W_WIN_RATE * rate, 1), W_WIN_RATE,
                     f"勝率 {won}/{closed}（{rate:.0%}）")


def _dim_quote_engagement(quotes: list[dict], orders: list[dict],
                          today: date) -> Dimension:
    if not quotes:
        return Dimension("quote_engagement", 0, W_QUOTE_ENGAGEMENT, "見積実績なし")
    recent = sum(1 for q in quotes if (_days_since(q.get("quoted_at"), today) or 999) <= 180)
    ordered_qids = {o.get("quote_id") for o in orders if o.get("quote_id")}
    converted = sum(1 for q in quotes if q.get("quote_id") in ordered_qids)
    conv = converted / len(quotes)
    pts = 5 * min(1.0, recent / 2) + 5 * conv
    return Dimension("quote_engagement", round(pts, 1), W_QUOTE_ENGAGEMENT,
                     f"見積 直近180日{recent}件 / 受注転換{converted}/{len(quotes)}（{conv:.0%}）")


def _dim_order_recency(orders: list[dict], today: date) -> Dimension:
    if not orders:
        return Dimension("order_recency", 0, W_ORDER_RECENCY, "受注実績なし")
    last_days = min((_days_since(o.get("ordered_at"), today) or 9999) for o in orders)
    recency = _clamp(8 * (540 - last_days) / 540, 0, 8)
    n = len(orders)
    repeat = 7 if n >= 3 else (4 if n == 2 else 2)
    pts = recency + repeat
    return Dimension("order_recency", round(pts, 1), W_ORDER_RECENCY,
                     f"受注{n}件 / 直近受注{last_days}日前")


def _dim_dm_access(open_deals: list[dict]) -> Dimension:
    if not open_deals:
        return Dimension("dm_access", W_DM_ACCESS / 2, W_DM_ACCESS, "進行中の案件なし")
    have = sum(1 for d in open_deals if d.get("decision_maker_identified"))
    share = have / len(open_deals)
    return Dimension("dm_access", round(W_DM_ACCESS * share, 1), W_DM_ACCESS,
                     f"決裁者特定 {have}/{len(open_deals)}件（{share:.0%}）")


def _dim_growth(orders: list[dict], today: date) -> Dimension:
    if not orders:
        return Dimension("growth", W_GROWTH / 2, W_GROWTH, "受注実績なし")

    def _rev(lo: int, hi: int) -> int:
        return sum(o.get("total_sales_amount", 0) or 0 for o in orders
                   if lo <= (_days_since(o.get("ordered_at"), today) or 99999) < hi)

    recent, prior = _rev(0, 180), _rev(180, 360)
    if prior == 0:
        pts = W_GROWTH if recent > 0 else W_GROWTH / 2
        trend = "新規/再開" if recent > 0 else "動きなし"
    else:
        pts = _clamp(W_GROWTH / 2 + W_GROWTH / 2 * (recent - prior) / prior, 0, W_GROWTH)
        trend = "増加" if recent >= prior else "減少"
    return Dimension("growth", round(pts, 1), W_GROWTH,
                     f"受注額 直近180日¥{recent:,} / 前180日¥{prior:,}（{trend}）")


def account_health(customer_id: str, today: date | None = None) -> AccountHealth:
    """Compute the account health score by rolling up the customer's deals,
    activities, quotes and orders. Pure/deterministic."""
    today = today or config.today()
    deals = store.deals_for_customer(customer_id)
    open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
    orders = store.orders_for_customer(customer_id)
    quotes = store.quotes_for_customer(customer_id)
    act_dates = [dt for dt in (_parse(a.get("activity_date"))
                               for a in store.activities_for_customer(customer_id)) if dt]

    dims = [
        _dim_activity_trend(act_dates, today),
        _dim_inactivity(act_dates, today),
        _dim_progression(open_deals),
        _dim_win_rate(deals),
        _dim_quote_engagement(quotes, orders, today),
        _dim_order_recency(orders, today),
        _dim_dm_access(open_deals),
        _dim_growth(orders, today),
    ]
    score = int(round(sum(d.points for d in dims)))
    band = "green" if score >= 70 else ("yellow" if score >= 45 else "red")
    return AccountHealth(score=score, band=band, dimensions=dims)
