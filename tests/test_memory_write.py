"""Write-side wiring: anchor a turn's observations to the entity in focus and
persist them — the free-insurance path that fills cross-chat memory as a byproduct
of the interpret pass the Reasoner already runs.

Covers the SessionFocus→EntityRef bridge, the persist API (anchoring, unanchored
skip, respecting a pre-set subject), and the injected LLMReasoner hook firing with
the observations Compose extracted (without ever breaking synthesis).
"""
from __future__ import annotations

from senpai.orchestration.memory import (
    JsonlObservationStore,
    remember_observations,
    subject_from_focus,
)
from senpai.orchestration.reason import EntityRef, LLMReasoner, Observation
from senpai.tools.focus import SessionFocus


def _obs(claim: str, subject: EntityRef | None = None) -> Observation:
    return Observation(claim=claim, kind="risk", materiality="high",
                       citations=("SPR D001",), confidence=0.8, subject=subject)


# --- subject_from_focus -------------------------------------------------------
def test_subject_prefers_deal_then_account_then_none():
    deal = subject_from_focus(SessionFocus(deal_id="D001", customer_id="C13"))
    assert deal == EntityRef(type="deal", id="D001", display=deal.display)
    assert deal.key == "deal:D001"

    acct = subject_from_focus(SessionFocus(customer_id="C13"))
    assert acct.type == "account" and acct.id == "C13"

    # A bare quote resolves no entity → nothing to anchor to.
    assert subject_from_focus(SessionFocus(last_quote="¥204,000")) is None
    assert subject_from_focus(SessionFocus()) is None
    assert subject_from_focus(None) is None


# --- remember_observations ----------------------------------------------------
def test_remember_anchors_and_persists(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    subject = EntityRef(type="deal", id="D001", display="村田印刷")
    n = remember_observations([_obs("a"), _obs("b")], subject=subject, store=store)
    assert n == 2
    got = store.by_subject(subject)
    assert {o.claim for o in got} == {"a", "b"}
    assert all(o.subject == subject for o in got)


def test_remember_skips_when_no_subject(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    # No subject passed, and no live conversation → session_focus() is empty → skip.
    from senpai.tools import conversation as conv
    conv.set_conversation(None)
    assert remember_observations([_obs("x")], store=store) == 0
    assert store.by_subject(EntityRef(type="deal", id="D001")) == []


def test_remember_respects_preanchored_observation(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    turn_subject = EntityRef(type="deal", id="D002")
    own = EntityRef(type="account", id="C99")
    remember_observations([_obs("keeps own subject", subject=own)],
                          subject=turn_subject, store=store)
    assert store.by_subject(own)[0].claim == "keeps own subject"   # its own anchor
    assert store.by_subject(turn_subject) == []                    # not the turn's


def test_remember_empty_is_noop(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    assert remember_observations([], subject=EntityRef(type="deal", id="D1"), store=store) == 0


# --- LLMReasoner hook ---------------------------------------------------------
def test_reasoner_hook_fires_with_extracted_observations(monkeypatch):
    """The injected hook receives exactly the observations Compose used — persistence
    rides the interpret pass, no extra model call."""
    import senpai.llm.client as client
    monkeypatch.setattr(client, "stream_complete", lambda messages, **kw: iter(["ok"]))

    seen: list = []
    r = LLMReasoner(on_observations=seen.extend)
    monkeypatch.setattr(r, "interpret", lambda view: [_obs("under-scoped")])

    out = "".join(r.stream({"fragments": []}, system="s", instruction="i"))
    assert out == "ok"
    assert [o.claim for o in seen] == ["under-scoped"]


def test_reasoner_hook_failure_never_breaks_synthesis(monkeypatch):
    import senpai.llm.client as client
    monkeypatch.setattr(client, "stream_complete", lambda messages, **kw: iter(["still answers"]))

    def boom(_obs):
        raise RuntimeError("store down")

    r = LLMReasoner(on_observations=boom)
    monkeypatch.setattr(r, "interpret", lambda view: [_obs("x")])
    out = "".join(r.stream({"fragments": []}, system="s", instruction="i"))
    assert out == "still answers"   # synthesis unaffected by a persistence fault


def test_reasoner_no_hook_when_no_observations(monkeypatch):
    import senpai.llm.client as client
    monkeypatch.setattr(client, "stream_complete", lambda messages, **kw: iter(["fallback"]))

    calls: list = []
    r = LLMReasoner(on_observations=calls.append)
    monkeypatch.setattr(r, "interpret", lambda view: [])   # nothing extracted
    "".join(r.stream({"fragments": []}, system="s", instruction="i"))
    assert calls == []   # hook not called with an empty set
