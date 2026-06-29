"""Per-agent gather plans for the crew, on the orchestration engine.

Each plan is the set of deterministic tools that agent ran inline before — same
tool, same args, same order, same human summary (so the `agent_tool` timeline is
unchanged). The engine now runs each agent's tools in parallel; the grounding is
reassembled in the fixed order the prompt expects, so the artifact is identical.

Task ids are the grounding slot names the agent reads back (snapshot/comparables/
notes/env, health, pipeline/at_risk).
"""
from __future__ import annotations

from senpai.orchestration import ExecutionPlan, Task


def _tool(task_id: str, op: str, inputs: dict, group: str, summary: str) -> Task:
    return Task(id=task_id, capability="tool", op=op, inputs=inputs,
                group=group, summary=summary)


def researcher_plan(deal_id: str, customer: str, industry: str) -> ExecutionPlan:
    return ExecutionPlan(tasks=(
        _tool("snapshot", "query_spr", {"deal_id": deal_id},
              "researcher", f"{deal_id} の案件サマリーと直近活動"),
        _tool("comparables", "find_similar_deals", {"customer": customer, "industry": industry},
              "researcher", "類似の成約事例を照合"),
        _tool("notes", "search_notes",
              {"customer": customer, "query": "課題 リスク 懸念 予算 決裁", "limit": 4},
              "researcher", "関連する日報の課題シグナル"),
        _tool("env", "lookup_customer_environment", {"customer": customer},
              "researcher", "顧客のIT環境"),
    ))


def coach_plan(deal_id: str) -> ExecutionPlan:
    return ExecutionPlan(tasks=(
        _tool("health", "score_deal_health", {"deal_id": deal_id},
              "coach", "健全性スコアとリスク信号"),
    ))


def rep_analyst_plan(rep_id: str, name: str) -> ExecutionPlan:
    return ExecutionPlan(tasks=(
        _tool("pipeline", "team_pipeline_overview", {"rep_id": rep_id},
              rep_id, f"{name} のパイプライン概況"),
        _tool("at_risk", "list_at_risk_deals", {"rep_id": rep_id, "band": "yellow", "limit": 5},
              rep_id, "要注意案件の抽出"),
    ))
