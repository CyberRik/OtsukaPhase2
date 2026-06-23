"""Expansion-opportunity detection for an account — deterministic rule engine.

Three families, all grounded in store records:
  * cross-sell — catalog categories the account has never bought, that are
    *complementary* to what it already owns (static adjacency map)
  * upsell     — environment upgrade triggers (aging OS, ADSL/更改検討中) on a
    customer that already buys in the relevant area
  * growth     — many open opportunities + low category coverage → strategic flag

The adjacency map and the env-trigger phrases are the only authored content;
everything else is read from orders/quotes/deals/environment. No LLM.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from senpai.data import store

# Major catalog categories (see products.json: the `major` field).
_ALL_CATEGORIES = {"OA機器", "PC周辺機器", "サーバー", "ストレージ",
                   "ソフトウェア", "ネットワーク機器", "役務"}

# What pairs well with what — owning the key suggests selling the values next.
_COMPLEMENTS: dict[str, list[str]] = {
    "OA機器": ["役務", "ソフトウェア", "ネットワーク機器"],
    "PC周辺機器": ["サーバー", "ソフトウェア", "ストレージ"],
    "サーバー": ["ストレージ", "ソフトウェア", "役務"],
    "ストレージ": ["サーバー", "ソフトウェア"],
    "ソフトウェア": ["役務", "サーバー"],
    "ネットワーク機器": ["役務", "サーバー", "ソフトウェア"],
}

# Environment phrases that explicitly flag an upgrade/refresh need.
_ENV_TRIGGERS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"ADSL|更改検討|更改予定|老朽|リプレース"), "ネットワーク機器",
     "ネットワークの更改サイン"),
    (re.compile(r"Windows\s*10|Windows\s*8|EOL|サポート終了"), "PC周辺機器",
     "OSのサポート終了/更新サイン"),
    (re.compile(r"無線LAN(?!.*有線)|Wi-?Fi"), "ネットワーク機器", "無線環境の増強余地"),
]


@dataclass
class Opportunity:
    kind: str            # cross_sell | upsell | growth
    target: str          # target product category
    rationale: str       # human, JA
    evidence: str        # what record this rests on
    confidence: str      # low | medium | high

    def to_dict(self) -> dict:
        return asdict(self)


def _category_of_order(o: dict) -> str | None:
    p = store.get_product(o.get("product_code", ""))
    return (p or {}).get("major")


def purchased_categories(customer_id: str) -> set[str]:
    """Categories the account has actually engaged on — ordered or quoted."""
    cats: set[str] = set()
    for o in store.orders_for_customer(customer_id):
        c = _category_of_order(o)
        if c:
            cats.add(c)
    for q in store.quotes_for_customer(customer_id):
        c = q.get("product_major_category")
        if c:
            cats.add(c)
    for d in store.deals_for_customer(customer_id):
        c = d.get("product_category")
        if c in _ALL_CATEGORIES:
            cats.add(c)
    return cats


def expansion_opportunities(customer_id: str) -> list[Opportunity]:
    owned = purchased_categories(customer_id)
    gaps = _ALL_CATEGORIES - owned
    deals = store.deals_for_customer(customer_id)
    from senpai import config
    open_n = sum(1 for d in deals if config.is_open_rank(d.get("order_rank")))
    out: list[Opportunity] = []

    # 1. cross-sell — gap categories complementary to something owned
    suggested: set[str] = set()
    for owned_cat in owned:
        for comp in _COMPLEMENTS.get(owned_cat, []):
            if comp in gaps and comp not in suggested:
                suggested.add(comp)
                out.append(Opportunity(
                    kind="cross_sell", target=comp,
                    rationale=f"{owned_cat}を購入済みだが{comp}は未導入",
                    evidence=f"購入カテゴリ: {owned_cat}",
                    confidence="medium"))

    # 2. upsell — environment upgrade triggers
    env = store.get_environment(customer_id) or {}
    hay = " ".join(str(env.get(k, "")) for k in ("pc", "os", "network", "notes"))
    for pat, target, why in _ENV_TRIGGERS:
        if pat.search(hay):
            out.append(Opportunity(
                kind="upsell", target=target,
                rationale=why,
                evidence=f"IT環境: {hay.strip()[:60]}",
                confidence="high" if target in owned else "medium"))

    # 3. growth — engaged account with open pipeline but thin coverage
    if open_n >= 2 and len(owned) <= 2:
        out.append(Opportunity(
            kind="growth", target="アカウント全体",
            rationale=f"進行中{open_n}件・取引カテゴリ{len(owned)}種 — 戦略アカウント候補",
            evidence=f"open deals={open_n}, categories={sorted(owned)}",
            confidence="medium"))

    return out
