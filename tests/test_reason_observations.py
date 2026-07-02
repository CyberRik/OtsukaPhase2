"""Interpret pass — the deterministic core of the two-pass Reasoner.

The LLM call itself needs a model, so here we exercise the GPU-free plumbing that
guards it: the citation firewall (no ungrounded claims reach the artifact), the
deterministic materiality ranking (the artifact leads with the lede reproducibly),
and the fail-safe fallback to single-shot synthesis when interpret yields nothing.
"""
from __future__ import annotations

import json

from senpai.orchestration.reason import (
    LLMReasoner,
    Observation,
    known_citations,
    parse_observations,
)

VIEW = {
    "run_id": "r1",
    "fragments": [
        {"capability": "crm", "op": "deal", "status": "ok", "confidence": 1.0,
         "citations": ["SPR D001"], "data": {"amount": 204000}},
        {"capability": "baselines", "op": "segment", "status": "ok", "confidence": 1.0,
         "citations": ["BASE seg-print"], "data": {"typical_amount": 340000}},
    ],
}


def test_known_citations_collects_all_handles():
    assert known_citations(VIEW) == {"SPR D001", "BASE seg-print"}


def test_firewall_drops_uncited_and_unknown_citations():
    raw = json.dumps([
        {"claim": "grounded judgment", "citations": ["SPR D001"], "materiality": "high"},
        {"claim": "no citations at all"},                              # dropped: uncited
        {"claim": "fabricated source", "citations": ["SPR D999"]},     # dropped: not in evidence
        {"claim": "", "citations": ["SPR D001"]},                      # dropped: empty claim
    ])
    obs = parse_observations(raw, known_citations(VIEW))
    assert [o.claim for o in obs] == ["grounded judgment"]
    assert obs[0].citations == ("SPR D001",)


def test_ranking_is_deterministic_by_materiality_then_confidence():
    raw = json.dumps([
        {"claim": "low", "citations": ["SPR D001"], "materiality": "low", "confidence": 0.9},
        {"claim": "high-b", "citations": ["SPR D001"], "materiality": "high", "confidence": 0.6},
        {"claim": "high-a", "citations": ["SPR D001"], "materiality": "high", "confidence": 0.8},
        {"claim": "medium", "citations": ["SPR D001"], "materiality": "medium", "confidence": 0.5},
    ])
    obs = parse_observations(raw, known_citations(VIEW))
    assert [o.claim for o in obs] == ["high-a", "high-b", "medium", "low"]


def test_parse_tolerates_prose_and_json_fence():
    raw = ("Here are the observations:\n```json\n"
           '[{"claim": "j", "citations": ["BASE seg-print"], "materiality": "medium"}]\n```')
    obs = parse_observations(raw, known_citations(VIEW))
    assert len(obs) == 1 and obs[0].kind == "fact"  # default kind applied


def test_parse_bad_json_yields_no_observations():
    assert parse_observations("not json at all", known_citations(VIEW)) == []
    assert parse_observations("", set()) == []


def test_interpret_skips_llm_when_nothing_citable():
    """No citations in the evidence → no interpret call at all (compose falls back)."""
    r = LLMReasoner()
    assert r.interpret({"run_id": "r", "fragments": [
        {"capability": "x", "op": "y", "status": "ok", "citations": [], "data": {}}]}) == []


def test_stream_falls_back_to_single_shot_without_observations(monkeypatch):
    """When interpret produces nothing, compose must still stream over the raw view —
    the two-pass split never regresses the original behavior."""
    import senpai.llm.client as client

    captured = {}

    def fake_stream_complete(messages, **kw):
        captured["prompt"] = messages[-1]["content"]
        yield "ok"

    monkeypatch.setattr(client, "stream_complete", fake_stream_complete)
    r = LLMReasoner(observe=False)  # skip interpret entirely
    out = "".join(r.stream(VIEW, system="s", instruction="do it"))
    assert out == "ok"
    assert "Evidence (JSON" in captured["prompt"]      # single-shot shape
    assert "observations" not in captured["prompt"].lower().split("evidence")[0]


def test_stream_composes_from_observations(monkeypatch):
    """When interpret yields observations, compose authors from them (they appear in
    the prompt ahead of the raw evidence)."""
    import senpai.llm.client as client

    captured = {}

    def fake_stream_complete(messages, **kw):
        captured["prompt"] = messages[-1]["content"]
        yield "drafted"

    monkeypatch.setattr(client, "stream_complete", fake_stream_complete)

    r = LLMReasoner()
    monkeypatch.setattr(r, "interpret", lambda view: [
        Observation(claim="under-scoped vs segment norm", kind="risk",
                    materiality="high", citations=("SPR D001",), confidence=0.8)])
    out = "".join(r.stream(VIEW, system="s", instruction="advise"))
    assert out == "drafted"
    assert "observations" in captured["prompt"]
    assert "under-scoped vs segment norm" in captured["prompt"]
