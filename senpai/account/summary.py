"""Account Summary Builder — one compact, grounded roll-up of a whole customer
relationship. Orchestrates health + trajectory + expansion and folds in the
headline aggregates a senior manager wants before talking about any single deal.

Pure/deterministic; every field traces to a store record. The API serializes
`to_dict()`; the commentary layer (account.context) renders the same object as a
text package for the model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from senpai import config
from senpai.data import store

from senpai.account.health import account_health, AccountHealth
from senpai.account.trajectory import relationship_trajectory, Pattern
from senpai.account.expansion import expansion_opportunities, Opportunity


@dataclass
class AccountSummary:
    customer_id: str
    customer: str
    industry: str
    size: str
    active_deals: int
    won_deals: int
    lost_deals: int
    total_pipeline: int          # ¥ open-deal amount
    historical_revenue: int      # ¥ sum of orders
    activity_trend: str          # human: 直近90日 N件 / 前90日 M件（増加/…）
    last_activity: str | None
    recent_quotes: list[dict] = field(default_factory=list)
    recent_orders: list[dict] = field(default_factory=list)
    environment: str | None = None
    health: dict = field(default_factory=dict)
    risk_signals: list[dict] = field(default_factory=list)
    expansion_signals: list[dict] = field(default_factory=list)
    recommended_focus: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except (ValueError, TypeError):
        return None


def _env_summary(customer_id: str) -> str | None:
    env = store.get_environment(customer_id)
    if not env:
        return None
    body = " / ".join(p for p in (env.get("pc"), env.get("os"), env.get("network")) if p)
    return body or None


def _recommended_focus(health: AccountHealth, patterns: list[Pattern],
                       opps: list[Opportunity]) -> str:
    """A single deterministic next-focus line, derived from the strongest signal.
    The LLM commentary elaborates; this guarantees a sensible answer even offline."""
    risks = [p for p in patterns if p.polarity == "risk"]
    if any(p.id == "multiple_stalled" for p in risks):
        return "停滞している複数案件の決裁ルートを確認し、停滞要因を切り分ける"
    if any(p.id == "engaged_no_progress" for p in risks):
        return "接触頻度ではなく、次の意思決定ステップを顧客と合意する"
    if any(p.id in ("loyal_dormant", "activity_declining", "spend_declining") for p in risks):
        return "常連顧客の関係維持のため、休眠化する前に再接触する"
    if opps:
        o = opps[0]
        return f"良好な関係を活かし、{o.target}の提案余地を探る（{o.rationale}）"
    if health.band == "green":
        return "健全な関係。既存案件を着実に前進させつつ、拡大余地を継続的に探る"
    return "活動を再開し、案件の現状と次の一手を顧客と確認する"


def build_account_summary(customer_id: str, today: date | None = None) -> AccountSummary | None:
    today = today or config.today()
    customer = store.get_customer(customer_id)
    if customer is None:
        return None

    deals = store.deals_for_customer(customer_id)
    open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
    won = sum(1 for d in deals if d.get("order_rank") in config.WON_RANKS)
    lost = sum(1 for d in deals if d.get("order_rank") in config.DEAD_RANKS)
    orders = store.orders_for_customer(customer_id)
    quotes = store.quotes_for_customer(customer_id)
    acts = store.activities_for_customer(customer_id)

    act_dates = [dt for dt in (_parse(a.get("activity_date")) for a in acts) if dt]
    recent = sum(1 for dt in act_dates if (today - dt).days < 90)
    prior = sum(1 for dt in act_dates if 90 <= (today - dt).days < 180)
    trend = "増加" if recent > prior else ("横ばい" if recent == prior else "減少")
    activity_trend = f"直近90日 {recent}件 / 前90日 {prior}件（{trend}）"
    last_activity = max(act_dates).isoformat() if act_dates else None

    health = account_health(customer_id, today=today)
    patterns = relationship_trajectory(customer_id, today=today)
    opps = expansion_opportunities(customer_id)

    return AccountSummary(
        customer_id=customer_id,
        customer=customer.get("name", customer_id),
        industry=customer.get("industry", "?"),
        size=customer.get("size", "?"),
        active_deals=len(open_deals),
        won_deals=won,
        lost_deals=lost,
        total_pipeline=sum(d.get("total_order_amount", 0) or 0 for d in open_deals),
        historical_revenue=sum(o.get("total_sales_amount", 0) or 0 for o in orders),
        activity_trend=activity_trend,
        last_activity=last_activity,
        recent_quotes=[
            {"quote_id": q.get("quote_id"), "amount": q.get("quote_amount"),
             "product": q.get("product_mid_category") or q.get("product_major_category"),
             "discount_rate": q.get("discount_rate"), "quoted_at": q.get("quoted_at"),
             "order_flag": q.get("order_flag")}
            for q in quotes[:3]
        ],
        recent_orders=[
            {"order_id": o.get("order_id"), "amount": o.get("total_sales_amount"),
             "product": o.get("product_name"), "ordered_at": o.get("ordered_at")}
            for o in orders[:3]
        ],
        environment=_env_summary(customer_id),
        health=health.to_dict(),
        risk_signals=[p.to_dict() for p in patterns if p.polarity == "risk"],
        expansion_signals=[o.to_dict() for o in opps]
        + [p.to_dict() for p in patterns if p.polarity == "positive"],
        recommended_focus=_recommended_focus(health, patterns, opps),
    )
