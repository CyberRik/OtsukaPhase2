"""Knowledge graph over the SPR store — customer→deal→activity→rep→product.

`build.graph()` materializes a networkx MultiDiGraph from the committed seed (cheap,
cached, rebuilt from the store so it never drifts); `query` exposes deterministic
multi-hop questions the keyword/semantic layers can't express (e.g. "which reps win
サーバー deals in 製造業 after a site survey"). GPU-free.
"""
from senpai.graph.build import graph, reload
from senpai.graph.query import (
    account_graph,
    connections,
    reps_who_win,
    similar_by_graph,
)

__all__ = [
    "graph", "reload",
    "reps_who_win", "account_graph", "connections", "similar_by_graph",
]
