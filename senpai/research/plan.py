"""research_plan() — the dependency graph for the research gather.

Two modes mirror the two legacy builders:
  * "customer" : all of a resolved customer's deals (was _build_research_bundle)
  * "deal"     : one deal in focus               (was _build_deal_context_bundle)

Level 0 (parallel): crm, activities, similar_deals, environment
Level 1:            health   (depends on crm + similar_deals)

`web_plan()` is the single-task not-found fallback.
"""
from __future__ import annotations

from senpai.orchestration import ExecutionPlan, Task

_GROUP = "research"


def research_plan(mode: str, *, customer_id: str, deal_id: str | None = None,
                  industry: str = "", today=None) -> ExecutionPlan:
    common = {"mode": mode, "customer_id": customer_id, "deal_id": deal_id}
    crm = Task(id="crm", capability="crm", inputs=common,
               group=_GROUP, summary="社内記録・案件を取得")
    activities = Task(id="activities", capability="activities", inputs=common,
                      group=_GROUP, summary="日報・活動履歴を取得")
    similar = Task(id="similar", capability="similar_deals",
                   inputs={"customer_id": customer_id, "industry": industry},
                   group=_GROUP, summary="類似の成約事例を照合")
    environment = Task(id="environment", capability="environment",
                       inputs={"customer_id": customer_id},
                       group=_GROUP, summary="IT環境を確認")
    health = Task(id="health", capability="health", inputs={"today": today},
                  depends_on=frozenset({"crm", "similar"}),
                  group=_GROUP, summary="案件の健全性を採点")
    return ExecutionPlan(tasks=(crm, activities, similar, environment, health))


def web_plan(query: str) -> ExecutionPlan:
    return ExecutionPlan(tasks=(
        Task(id="web", capability="web", inputs={"query": query},
             group=_GROUP, summary="Web検索でカバー"),
    ))
