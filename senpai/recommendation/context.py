"""`RecommendationContext` — everything known about an account, gathered once and
handed to any domain's candidate generator. Domain-agnostic: it's "what do we
know," not "what should we suggest" — a solutions generator and a future actions
generator read the same context differently, neither owns it.

Built deterministically from the store (never from free text/LLM guesses) —
same "never invent an ID" rule the document planner enforces in `selection.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from senpai.account.expansion import Opportunity, expansion_opportunities
from senpai.data import store


@dataclass(frozen=True)
class RecommendationContext:
    customer_id: str
    deal_id: str = ""
    customer_name: str = ""
    industry: str = ""
    category: str = ""                          # the resolved deal's product_category, if any
    environment: dict[str, str] = field(default_factory=dict)
    opportunities: tuple[Opportunity, ...] = ()  # account.expansion's deterministic signals
    owned_categories: tuple[str, ...] = ()       # categories with a real order/quote/deal on file


def build_context(customer_id: str, deal_id: str = "") -> RecommendationContext | None:
    """Resolve a context deterministically from the store. Returns None when
    `customer_id` doesn't resolve — callers decide how to degrade (never widen
    to a guessed account)."""
    customer = store.get_customer(customer_id)
    if customer is None:
        return None

    deal: dict[str, Any] | None = store.get_deal(deal_id) if deal_id else None
    if deal is None and not deal_id:
        # No deal named — use the account's largest open deal, same preference
        # order as the document planner's own entity resolution.
        from senpai import config
        deals = store.deals_for_customer(customer_id)
        open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
        pool = sorted(open_deals or deals, key=lambda d: d.get("total_order_amount", 0), reverse=True)
        deal = pool[0] if pool else None

    from senpai.account.expansion import purchased_categories
    env = store.get_environment(customer_id) or {}

    return RecommendationContext(
        customer_id=customer_id,
        deal_id=(deal or {}).get("deal_id", deal_id),
        customer_name=customer.get("name", ""),
        industry=customer.get("industry", ""),
        category=(deal or {}).get("product_category", ""),
        environment={k: v for k, v in env.items() if v},
        opportunities=tuple(expansion_opportunities(customer_id)),
        owned_categories=tuple(sorted(purchased_categories(customer_id))),
    )
