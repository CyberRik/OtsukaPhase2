"""Extension seam: the Reasoner interface — the single synthesis over a bundle.

A Reasoner consumes a reasoner-view (from the bundle, optionally reduced) and
streams the final artifact text. It is the ONE place reasoning happens; capabilities
never reason.

Reasoning is two passes inside this one stage (no new orchestration upstream):

  1. **Interpret** — the evidence view becomes a small set of typed, *cited*
     `Observation`s (judgments, not restatements). Temp 0, structured JSON. Any
     observation whose citations don't trace back to the evidence is dropped: an
     uncited claim is a hallucination, so it never reaches the artifact.
  2. **Compose** — the artifact is authored *from the ranked observations* (with the
     raw evidence still available for exact figures/handles), not from raw records.

Splitting reading/judging from writing is what makes output read like a senior rep
instead of "LLM + retrieval". If Interpret yields nothing usable (or the model is
unavailable) Compose falls back to the original single-shot synthesis — no regression.

M0 ships `EchoReasoner` (deterministic, GPU-free — for tests and the self-check)
and `LLMReasoner`, a thin wrapper over the existing `senpai.llm.client` that M1
wires into the routes. Swapping reasoner implementations changes nothing upstream.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator, Protocol


class Reasoner(Protocol):
    def stream(self, view: dict, *, system: str, instruction: str) -> Iterator[str]:
        ...


# --- the reasoning representation ---------------------------------------------

_MATERIALITY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class EntityRef:
    """What an observation is *about* — the anchor that makes it addressable across
    chats. A deal/account/contact/product resolved to a real id (from a tool result),
    never a fuzzy name. `key` is the stable lookup handle a store indexes on."""
    type: str            # account | deal | contact | product
    id: str
    display: str = ""

    @property
    def key(self) -> str:
        return f"{self.type}:{self.id}"

    def as_dict(self) -> dict:
        return {"type": self.type, "id": self.id, "display": self.display}

    @classmethod
    def from_dict(cls, raw: dict | None) -> "EntityRef | None":
        if not isinstance(raw, dict) or not raw.get("type") or not raw.get("id"):
            return None
        return cls(type=str(raw["type"]), id=str(raw["id"]),
                   display=str(raw.get("display") or ""))


@dataclass(frozen=True)
class Observation:
    """One judgment the evidence supports — an interpretation, not a restatement
    ("¥204,000 is ~40% below this segment's typical deal → likely under-scoped").
    Every observation must cite the evidence handle(s) it rests on; an uncited
    observation is dropped before it can reach the artifact.

    `subject` + `as_of` are the cross-chat spine: what this judgment is about, and
    when it was reached — so a later chat about the same deal can reason from it.
    They default empty; a same-chat/artifact synthesis needs neither."""
    claim: str
    kind: str = "fact"          # fact | risk | opportunity | gap | action
    materiality: str = "medium"  # high | medium | low
    citations: tuple[str, ...] = ()
    confidence: float = 0.5
    subject: EntityRef | None = None
    as_of: str = ""             # ISO-8601 UTC; stamped on persist if unset

    def as_dict(self) -> dict:
        return {"claim": self.claim, "kind": self.kind,
                "materiality": self.materiality,
                "citations": list(self.citations),
                "confidence": self.confidence,
                "subject": self.subject.as_dict() if self.subject else None,
                "as_of": self.as_of}

    @classmethod
    def from_dict(cls, raw: dict) -> "Observation":
        if not isinstance(raw, dict) or not str(raw.get("claim") or "").strip():
            raise ValueError("observation record missing claim")
        cites = raw.get("citations") or []
        if isinstance(cites, str):
            cites = [cites]
        try:
            confidence = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return cls(
            claim=str(raw["claim"]),
            kind=str(raw.get("kind") or "fact"),
            materiality=str(raw.get("materiality") or "medium"),
            citations=tuple(c for c in cites if isinstance(c, str)),
            confidence=confidence,
            subject=EntityRef.from_dict(raw.get("subject")),
            as_of=str(raw.get("as_of") or ""),
        )


def known_citations(view: dict) -> set[str]:
    """Every citation handle the evidence actually offers — the whitelist the
    interpret pass is held to."""
    out: set[str] = set()
    for f in view.get("fragments", []):
        out.update(c for c in f.get("citations", []) if isinstance(c, str))
    return out


def _coerce_obs(raw: dict, allowed: set[str]) -> Observation | None:
    """One parsed JSON object → a validated Observation, or None if it can't stand
    (no claim, or no citation that traces back to the evidence)."""
    if not isinstance(raw, dict):
        return None
    claim = str(raw.get("claim") or "").strip()
    if not claim:
        return None
    cites = raw.get("citations") or []
    if isinstance(cites, str):
        cites = [cites]
    # Firewall: keep only citations the evidence actually provided. If nothing
    # survives, the claim is ungrounded — drop it entirely.
    cites = tuple(c for c in cites if isinstance(c, str) and c in allowed)
    if not cites:
        return None
    kind = str(raw.get("kind") or "fact").strip().lower()
    materiality = str(raw.get("materiality") or "medium").strip().lower()
    if materiality not in _MATERIALITY_RANK:
        materiality = "medium"
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return Observation(claim=claim, kind=kind, materiality=materiality,
                       citations=cites, confidence=confidence)


def _extract_json_array(text: str):
    """Pull the first JSON array out of an LLM reply (which may wrap it in prose or
    a ```json fence). Returns a list or None."""
    if not text:
        return None
    text = text.strip().strip("`")
    if text.startswith("json"):
        text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        val = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    return val if isinstance(val, list) else None


def parse_observations(raw: str, allowed: set[str]) -> list[Observation]:
    """Parse the interpret reply into validated, *deterministically ranked*
    observations. Ranking (materiality, then confidence) is deterministic so the
    artifact leads with the lede reproducibly — the reasoning, not the model's
    output order, decides what comes first. Uncited claims are dropped."""
    arr = _extract_json_array(raw)
    if not arr:
        return []
    obs = [o for o in (_coerce_obs(r, allowed) for r in arr) if o is not None]
    obs.sort(key=lambda o: (_MATERIALITY_RANK[o.materiality], -o.confidence))
    return obs


_INTERPRET_SYSTEM = (
    "You are a senior B2B sales analyst. Read the structured evidence and extract "
    "the JUDGMENTS a seasoned rep would draw from it — risks, opportunities, gaps, "
    "and material facts — NOT a restatement of the records. Compare figures against "
    "any baselines present. Return ONLY a JSON array of objects with keys: "
    "claim (string, the judgment), kind (fact|risk|opportunity|gap|action), "
    "materiality (high|medium|low), citations (array of the evidence citation "
    "handles this claim rests on — use the exact strings from the evidence), "
    "confidence (0..1). Every object MUST cite at least one evidence handle. "
    "Omit anything the evidence does not support. No prose outside the JSON array."
)


# --- reasoners ----------------------------------------------------------------

class EchoReasoner:
    """Deterministic, no-LLM. Emits a compact textual digest of the evidence — used
    by the self-test and any unit test that must not hit a model."""

    def stream(self, view: dict, *, system: str = "", instruction: str = "") -> Iterator[str]:
        frags = view.get("fragments", [])
        yield f"{len(frags)} evidence fragment(s):\n"
        for f in frags:
            cites = ", ".join(f.get("citations", [])) or "-"
            yield f"- [{f.get('capability')}/{f.get('op')}] {json.dumps(f.get('data'), ensure_ascii=False)} (出典: {cites})\n"


class LLMReasoner:
    """Routed synthesis via the existing client. Two passes (interpret → compose)
    with a single-shot fallback. Lazy import so M0 stays import-light and GPU-free
    until a route actually reasons."""

    def __init__(self, *, no_think: bool = True, max_tokens: int = 1200,
                 temperature: float = 0.3, observe: bool = True,
                 max_observations: int = 12) -> None:
        self.no_think = no_think
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.observe = observe
        self.max_observations = max_observations

    def interpret(self, view: dict) -> list[Observation]:
        """Pass A: evidence view → cited, ranked observations. Deterministic (temp 0)
        and fail-safe — any error yields an empty list so Compose falls back."""
        allowed = known_citations(view)
        if not allowed:
            return []  # nothing citable → nothing to interpret; compose raw
        from senpai.llm.client import simple_complete  # lazy
        prompt = ("Evidence (JSON, structured — reason only over this):\n"
                  + json.dumps(view, ensure_ascii=False, indent=2))
        try:
            raw = simple_complete(
                [{"role": "system", "content": _INTERPRET_SYSTEM},
                 {"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=self.max_tokens,
                no_think=self.no_think, allow_fallback=False,
            )
        except Exception:
            return []
        return parse_observations(raw, allowed)[: self.max_observations]

    def stream(self, view: dict, *, system: str, instruction: str) -> Iterator[str]:
        from senpai.llm.client import stream_complete  # lazy

        observations = self.interpret(view) if self.observe else []
        if observations:
            # Compose from the ranked judgments; keep the raw evidence available so
            # exact figures and citation handles are quoted, not paraphrased.
            payload = {
                "observations": [o.as_dict() for o in observations],
                "evidence": view,
            }
            prompt = (
                f"{instruction}\n\n"
                "Author the response from these ranked observations (most material "
                "first). State the judgments and their implications — do not merely "
                "list the evidence. Quote figures and citation handles exactly from "
                "the evidence block.\n\n"
                f"Observations + evidence (JSON):\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
            )
        else:
            # Fallback: original single-shot synthesis over the raw evidence view.
            prompt = (f"{instruction}\n\n"
                      f"Evidence (JSON, structured — use only this):\n"
                      f"{json.dumps(view, ensure_ascii=False, indent=2)}")

        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        yield from stream_complete(
            messages, temperature=self.temperature, max_tokens=self.max_tokens,
            no_think=self.no_think, allow_fallback=False,
        )
