"""Materialize the SPR knowledge graph from the store.

Nodes (each carries `kind`):
    rep (R..) · customer (C..) · deal (D..) · product (code)
    industry:<name> · category:<major> · acttype:<activity_type>   (grouping nodes)
Edges (each carries `rel`):
    rep   -OWNS->        deal
    deal  -FOR->         customer
    deal  -CONCERNS->    product
    deal  -IN_CATEGORY-> category:<major>
    deal  -HAD->         acttype:<activity_type>
    customer -IN_INDUSTRY-> industry:<name>

Deal nodes are denormalized with the attributes the multi-hop queries filter on
(category, industry, outcome, amount, rep, products, acttypes) so traversal stays a
simple, fast, deterministic scan — the networkx edges back relational queries
(connections/paths, neighborhoods). Built from the committed seed and cached, so it
always matches the data with no separate artifact to regenerate.
"""
from __future__ import annotations

from functools import lru_cache

import networkx as nx

from senpai import config
from senpai.data import store


def _outcome(rank: str | None) -> str:
    if rank in config.WON_RANKS:
        return "won"
    if rank in config.DEAD_RANKS:
        return "lost"
    return "open"


@lru_cache(maxsize=1)
def graph() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()

    for r in store.all_reps():
        G.add_node(r["employee_id"], kind="rep", name=r.get("name", ""),
                   role=r.get("role", ""), department=r.get("department", ""),
                   specialty_tags=tuple(r.get("specialty_tags", [])))

    for c in store.all_customers():
        cid = c["customer_id"]
        ind = c.get("industry", "")
        G.add_node(cid, kind="customer", name=c.get("name", ""),
                   industry=ind, size=c.get("size", ""))
        if ind:
            G.add_node(f"industry:{ind}", kind="industry")
            G.add_edge(cid, f"industry:{ind}", rel="IN_INDUSTRY")

    for p in store.all_products():
        code = p["product_code"]
        major = p.get("major", "")
        G.add_node(code, kind="product", name=p.get("product_name", ""),
                   major=major, mid=p.get("mid", ""))
        if major:
            G.add_node(f"category:{major}", kind="category")

    for d in store.all_deals():
        did = d["deal_id"]
        cid = d.get("customer_id", "")
        cat = d.get("product_category", "")
        cust = store.get_customer(cid) or {}
        acttypes = tuple(sorted({a.get("activity_type", "")
                                 for a in store.activities_for_deal(did)
                                 if a.get("activity_type")}))
        rep = store.deal_rep_id(d)
        G.add_node(did, kind="deal", name=d.get("deal_name", ""),
                   rank=d.get("order_rank", ""), outcome=_outcome(d.get("order_rank")),
                   amount=d.get("total_order_amount", 0) or 0,
                   category=cat, industry=cust.get("industry", ""),
                   rep=rep, products=tuple(d.get("products", [])), acttypes=acttypes)
        if rep:
            G.add_edge(rep, did, rel="OWNS")
        if cid:
            G.add_edge(did, cid, rel="FOR")
        if cat:
            G.add_node(f"category:{cat}", kind="category")
            G.add_edge(did, f"category:{cat}", rel="IN_CATEGORY")
        for pc in d.get("products", []):
            G.add_edge(did, pc, rel="CONCERNS")
        for t in acttypes:
            G.add_node(f"acttype:{t}", kind="acttype")
            G.add_edge(did, f"acttype:{t}", rel="HAD")

    return G


def reload() -> None:
    """Drop the cached graph (tests / after the seed is regenerated)."""
    graph.cache_clear()


def deal_nodes(G: nx.MultiDiGraph | None = None):
    """Iterate (deal_id, attrs) for every deal node."""
    G = G or graph()
    return [(n, a) for n, a in G.nodes(data=True) if a.get("kind") == "deal"]


def stats() -> dict:
    """Node/edge counts by kind/rel — handy for tests and a build summary."""
    G = graph()
    kinds: dict[str, int] = {}
    for _n, a in G.nodes(data=True):
        kinds[a.get("kind", "?")] = kinds.get(a.get("kind", "?"), 0) + 1
    rels: dict[str, int] = {}
    for _u, _v, a in G.edges(data=True):
        rels[a.get("rel", "?")] = rels.get(a.get("rel", "?"), 0) + 1
    return {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
            "by_kind": kinds, "by_rel": rels}


if __name__ == "__main__":
    import json
    print(json.dumps(stats(), ensure_ascii=False, indent=2))
