"""Cross-chat memory stub — the ObservationStore seam.

Proves the read/write path works end-to-end on the JSONL stub before the DB exists:
round-trip, subject filtering, newest-first ordering, unanchored-skip, persistence
across store instances (i.e. across chats/restarts), and robustness to bad lines. The
DB implementation must satisfy the same contract.
"""
from __future__ import annotations

from senpai.orchestration.memory import JsonlObservationStore
from senpai.orchestration.reason import EntityRef, Observation

D001 = EntityRef(type="deal", id="D001", display="村田印刷")
D002 = EntityRef(type="deal", id="D002")


def _obs(claim: str, subject: EntityRef | None, as_of: str = "") -> Observation:
    return Observation(claim=claim, kind="risk", materiality="high",
                       citations=("SPR D001",), confidence=0.8,
                       subject=subject, as_of=as_of)


def test_put_then_by_subject_roundtrips(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    store.put(_obs("under-scoped vs segment norm", D001, as_of="2026-01-10T00:00:00+00:00"))

    got = store.by_subject(D001)
    assert len(got) == 1
    o = got[0]
    assert o.claim == "under-scoped vs segment norm"
    assert o.subject is not None and o.subject.key == "deal:D001"
    assert o.subject.display == "村田印刷"      # EntityRef survives the round-trip
    assert o.citations == ("SPR D001",)
    assert o.materiality == "high" and o.confidence == 0.8


def test_by_subject_filters_and_orders_newest_first(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    store.put(_obs("older D001", D001, as_of="2026-01-01T00:00:00+00:00"))
    store.put(_obs("about a different deal", D002, as_of="2026-02-01T00:00:00+00:00"))
    store.put(_obs("newer D001", D001, as_of="2026-03-01T00:00:00+00:00"))

    got = store.by_subject(D001)
    assert [o.claim for o in got] == ["newer D001", "older D001"]  # newest-first, D002 excluded

    limited = store.by_subject(D001, limit=1)
    assert [o.claim for o in limited] == ["newer D001"]


def test_put_stamps_as_of_when_missing(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    store.put(_obs("no timestamp given", D001))  # as_of=""
    got = store.by_subject(D001)
    assert len(got) == 1 and got[0].as_of  # stamped on persist


def test_unanchored_observation_is_not_stored(tmp_path):
    store = JsonlObservationStore(tmp_path / "obs.jsonl")
    store.put(_obs("no subject → not cross-chat addressable", subject=None))
    assert store.by_subject(D001) == []
    assert not (tmp_path / "obs.jsonl").exists()  # nothing written at all


def test_persists_across_store_instances(tmp_path):
    """A new store over the same file sees prior observations — this is what makes it
    'cross-chat' (a fresh chat/process reads what an earlier one wrote)."""
    path = tmp_path / "obs.jsonl"
    JsonlObservationStore(path).put(_obs("written in chat A", D001, as_of="2026-01-01T00:00:00+00:00"))
    reopened = JsonlObservationStore(path)
    assert [o.claim for o in reopened.by_subject(D001)] == ["written in chat A"]


def test_by_subject_missing_file_is_empty(tmp_path):
    assert JsonlObservationStore(tmp_path / "nope.jsonl").by_subject(D001) == []


def test_malformed_lines_are_skipped(tmp_path):
    path = tmp_path / "obs.jsonl"
    store = JsonlObservationStore(path)
    store.put(_obs("valid", D001, as_of="2026-01-01T00:00:00+00:00"))
    with path.open("a", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write('{"kind": "risk"}\n')   # valid json, but no claim → dropped by from_dict
        f.write("\n")                     # blank line
    got = store.by_subject(D001)
    assert [o.claim for o in got] == ["valid"]  # only the good record survives


def test_entityref_from_dict_rejects_incomplete():
    assert EntityRef.from_dict(None) is None
    assert EntityRef.from_dict({"type": "deal"}) is None      # no id
    assert EntityRef.from_dict({"id": "D001"}) is None        # no type
    ref = EntityRef.from_dict({"type": "deal", "id": "D001"})
    assert ref is not None and ref.key == "deal:D001"
