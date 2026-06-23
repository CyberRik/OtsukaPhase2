"""Deterministic multi-hop queries over the SPR knowledge graph.

These answer relational questions the keyword/semantic layers can't — e.g. "which
reps win サーバー deals in 製造業 after a site survey", an account's whole neighborhood,
or how two entities connect. Parameterized (not free-form Cypher) so results are
explainable and safe. All GPU-free; backed by senpai.graph.build.graph().
"""
from __future__ import annotations

import networkx as nx

from senpai.data import store
from senpai.graph.build import deal_nodes, graph


def reps_who_win(category: str = "", industry: str = "",
                 after_activity_type: str = "", min_deals: int = 1) -> list[dict]:
    """Reps ranked by win-rate on *closed* deals matching the given filters
    (category / customer-industry / having had an activity type). Each row carries
    won/closed counts and a few example deal ids — the differentiating evidence."""
    G = graph()
    agg: dict[str, dict] = {}
    for did, a in deal_nodes(G):
        if a.get("outcome") == "open":
            continue  # only won/lost deals carry a win/loss signal
        if category and category not in (a.get("category") or ""):
            continue
        if industry and industry not in (a.get("industry") or ""):
            continue
        if after_activity_type and not any(
                after_activity_type in t for t in a.get("acttypes", ())):
            continue
        rep = a.get("rep") or "?"
        v = agg.setdefault(rep, {"won": 0, "closed": 0, "deals": []})
        v["closed"] += 1
        v["deals"].append(did)
        if a.get("outcome") == "won":
            v["won"] += 1

    rows = []
    for rep, v in agg.items():
        if v["closed"] < max(1, int(min_deals)):
            continue
        rows.append({
            "rep_id": rep, "rep_name": store.rep_name(rep),
            "won": v["won"], "closed": v["closed"],
            "win_rate": round(v["won"] / v["closed"], 3) if v["closed"] else 0.0,
            "example_deal_ids": sorted(v["deals"])[:6],
        })
    rows.sort(key=lambda r: (r["win_rate"], r["won"], r["closed"]), reverse=True)
    return rows


def account_graph(customer: str) -> dict:
    """The neighborhood of one account: its deals, the reps on them, and the
    products in play — a one-call relational brief."""
    c = store.resolve_customer(customer)
    if not c:
        return {"status": "not_found", "query": customer}
    cid = c["customer_id"]
    G = graph()
    deal_ids = [u for u, _v, d in G.in_edges(cid, data=True) if d.get("rel") == "FOR"]
    deals, reps, products = [], set(), set()
    for did in deal_ids:
        a = G.nodes[did]
        deals.append({"deal_id": did, "name": a.get("name", ""), "rank": a.get("rank", ""),
                      "outcome": a.get("outcome", ""), "amount": a.get("amount", 0)})
        if a.get("rep"):
            reps.add(a["rep"])
        products.update(a.get("products", ()))
    deals.sort(key=lambda d: d["deal_id"])
    return {
        "status": "found", "customer_id": cid, "name": c.get("name", ""),
        "industry": c.get("industry", ""), "size": c.get("size", ""),
        "deals": deals,
        "reps": [{"rep_id": r, "name": store.rep_name(r)} for r in sorted(reps)],
        "products": [{"code": p, "name": (store.get_product(p) or {}).get("product_name", p)}
                     for p in sorted(products)],
    }


def _resolve_node(entity: str) -> str | None:
    """Map a free-form entity (node id, customer name, product name, rep name) to a
    graph node id."""
    G = graph()
    if entity in G:
        return entity
    c = store.resolve_customer(entity)
    if c:
        return c["customer_id"]
    low = (entity or "").strip().lower()
    for n, a in G.nodes(data=True):
        if a.get("kind") in ("product", "rep") and low and low in (a.get("name", "").lower()):
            return n
    return None


def _describe(node: str) -> dict:
    a = graph().nodes[node]
    return {"id": node, "kind": a.get("kind", ""), "label": a.get("name", node)}


def connections(entity_a: str, entity_b: str) -> dict:
    """Shortest relational path between two entities (e.g. a product and a customer,
    via the reps/deals that connect them)."""
    ua, ub = _resolve_node(entity_a), _resolve_node(entity_b)
    if not ua or not ub:
        return {"status": "not_found", "a": entity_a, "b": entity_b}
    UG = graph().to_undirected(as_view=True)
    try:
        path = nx.shortest_path(UG, ua, ub)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {"status": "no_path", "a": entity_a, "b": entity_b}
    return {"status": "found", "hops": len(path) - 1, "path": [_describe(n) for n in path]}


def similar_by_graph(deal_id: str, limit: int = 5) -> list[dict]:
    """Deals related to `deal_id` through shared rep / product / industry / category —
    a graph-based complement to the feature-match find_similar_deals."""
    G = graph()
    base = G.nodes.get(deal_id)
    if not base or base.get("kind") != "deal":
        return []
    rep, cat, ind = base.get("rep"), base.get("category"), base.get("industry")
    prods = set(base.get("products", ()))
    scored = []
    for did, a in deal_nodes(G):
        if did == deal_id:
            continue
        s = 0
        if rep and a.get("rep") == rep:
            s += 1
        s += len(prods & set(a.get("products", ()))) * 2
        if cat and a.get("category") == cat:
            s += 1
        if ind and a.get("industry") == ind:
            s += 1
        if s:
            scored.append((s, did, a))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [{"deal_id": did, "name": a.get("name", ""), "outcome": a.get("outcome", ""),
             "score": s} for s, did, a in scored[:limit]]


if __name__ == "__main__":
    import json
    print("reps_who_win(category='サーバー'):")
    print(json.dumps(reps_who_win(category="サーバー")[:5], ensure_ascii=False, indent=2))
