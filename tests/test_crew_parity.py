"""M2 golden regression: the crew's gather now runs on the orchestration engine; it
must reproduce the legacy inline gather and the legacy `agent_tool` timeline.

Like M1, prose is non-deterministic, so we prove the *grounding fed to each agent is
identical* (same tool strings, same order) and the *event timeline is unchanged*
(same agent_tool name/summary/order). An end-to-end test with the LLM stubbed proves
the full /crew event sequence (crew → agents+tools → strategist → final → done) is
preserved.
"""
from __future__ import annotations

import pytest

from senpai.agent import crew
from senpai.agent.gather import run_agent_gather
from senpai.agent.plan import coach_plan, rep_analyst_plan, researcher_plan
from senpai.data import store
from senpai.tools import impl


def _deals(n=30):
    return store.open_deals()[:n]


def _legacy_researcher_grounding(d):
    customer = store.customer_name(d["customer_id"])
    industry = (store.get_customer(d["customer_id"]) or {}).get("industry", "")
    return {
        "snapshot": impl.query_spr(deal_id=d["deal_id"]),
        "comparables": impl.find_similar_deals_tool(customer=customer, industry=industry),
        "notes": impl.search_notes(customer=customer, query="課題 リスク 懸念 予算 決裁", limit=4),
        "env": impl.lookup_customer_environment(customer=customer),
    }


# ── researcher gather: identical strings + identical agent_tool timeline ─────
@pytest.mark.parametrize("deal", _deals(), ids=lambda d: d["deal_id"])
def test_researcher_gather_parity(deal):
    customer = store.customer_name(deal["customer_id"])
    industry = (store.get_customer(deal["customer_id"]) or {}).get("industry", "")
    events: list[dict] = []
    g = run_agent_gather(researcher_plan(deal["deal_id"], customer, industry),
                         "researcher", events.append)

    assert g == _legacy_researcher_grounding(deal)

    tools = [(e["agent_id"], e["name"], e["summary"]) for e in events
             if e["type"] == "agent_tool"]
    assert tools == [
        ("researcher", "query_spr", f"{deal['deal_id']} の案件サマリーと直近活動"),
        ("researcher", "find_similar_deals", "類似の成約事例を照合"),
        ("researcher", "search_notes", "関連する日報の課題シグナル"),
        ("researcher", "lookup_customer_environment", "顧客のIT環境"),
    ]


# ── coach gather ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("deal", _deals(), ids=lambda d: d["deal_id"])
def test_coach_gather_parity(deal):
    events: list[dict] = []
    g = run_agent_gather(coach_plan(deal["deal_id"]), "coach", events.append)
    assert g["health"] == impl.score_deal_health(deal_id=deal["deal_id"])
    tools = [(e["agent_id"], e["name"], e["summary"]) for e in events
             if e["type"] == "agent_tool"]
    assert tools == [("coach", "score_deal_health", "健全性スコアとリスク信号")]


# ── manager fan-out: one rep analyst ────────────────────────────────────────
def test_rep_analyst_gather_parity():
    reps = crew._rep_roster(limit=3)
    assert reps
    for rep_id in reps:
        name = store.rep_name(rep_id)
        events: list[dict] = []
        g = run_agent_gather(rep_analyst_plan(rep_id, name), rep_id, events.append)
        assert g["pipeline"] == impl.team_pipeline_overview(rep_id=rep_id)
        assert g["at_risk"] == impl.list_at_risk_deals(rep_id=rep_id, band="yellow", limit=5)
        tools = [(e["agent_id"], e["name"]) for e in events if e["type"] == "agent_tool"]
        assert tools == [(rep_id, "team_pipeline_overview"), (rep_id, "list_at_risk_deals")]


# ── partial failure: gather degrades, never crashes ─────────────────────────
def test_gather_degrades_on_tool_failure(monkeypatch):
    import senpai.agent.capabilities as caps
    real = caps.impl.dispatch

    def flaky(name, args):
        if name == "search_notes":
            raise RuntimeError("simulated retrieval outage")
        return real(name, args)

    monkeypatch.setattr(caps.impl, "dispatch", flaky)
    deal = _deals(1)[0]
    customer = store.customer_name(deal["customer_id"])
    g = run_agent_gather(researcher_plan(deal["deal_id"], customer, ""), "researcher",
                         lambda _e: None)
    assert g["notes"] == ""          # the failed slot degrades to empty
    assert g["snapshot"] and g["env"]  # the rest still gathered


# ── end-to-end: full /crew event sequence preserved (LLM stubbed) ───────────
def test_run_crew_event_sequence(monkeypatch):
    monkeypatch.setattr(crew.client, "simple_complete",
                        lambda *a, **k: "STUB")
    deal = _deals(1)[0]
    events = list(crew.run_crew(deal["deal_id"]))
    types = [e["type"] for e in events]

    assert types[0] == "crew"
    assert events[0]["agents"] == crew.AGENTS
    assert types[-1] == "done"
    assert "final" in types
    # both fact-gatherers ran with their tools, plus the strategist
    started = {e["id"] for e in events if e["type"] == "agent" and e["status"] == "running"}
    assert {"researcher", "coach", "strategist"} <= started
    done = {e["id"] for e in events if e["type"] == "agent" and e["status"] == "done"}
    assert {"researcher", "coach", "strategist"} <= done
    tool_agents = {e["agent_id"] for e in events if e["type"] == "agent_tool"}
    assert {"researcher", "coach"} <= tool_agents
    final = next(e for e in events if e["type"] == "final")
    assert final["markdown"] == "STUB"
