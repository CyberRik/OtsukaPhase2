"""Data model for the knowledge-expansion pipeline + (de)serialisation.

Everything is plain dataclasses over JSON-friendly dicts so the store is a couple
of committed JSON files — auditable in a diff, no DB. Confidence is *computed*,
never authored, so it can't be inflated by hand.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# --- status / confidence vocabularies (kept as plain strings for JSON) -------
STATUS_DRAFT = "draft"            # generated, not yet human-reviewed
STATUS_APPROVED = "approved"      # a human confirmed it stays within the principle
STATUS_NEEDS_EDIT = "needs_edit"  # close, but a reviewer asked for changes
STATUS_REJECTED = "rejected"      # off-principle / hallucinated → never shown

REVIEWABLE = {STATUS_DRAFT, STATUS_APPROVED, STATUS_NEEDS_EDIT, STATUS_REJECTED}

CONF_HIGH = "high"            # approved + principle backed by >=2 interviews
CONF_MEDIUM = "medium"        # approved + 1 interview, or corroborated by survey
CONF_LOW = "low"              # approved but thinly sourced (1 interview, no backup)
CONF_UNVERIFIED = "unverified"  # not approved, or failed grounding → not shown


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Layer 0 — raw source
# ---------------------------------------------------------------------------
@dataclass
class Source:
    source_id: str               # 'I01' interview, 'S01' survey
    kind: str                    # 'interview' | 'survey'
    participant_role: str        # e.g. 'senior', 'expert' — never a name in code
    date: str = ""
    uri: str = ""                # where the raw transcript/response lives
    notes: str = ""


# ---------------------------------------------------------------------------
# Layer 1 — validated principle (the ground truth GenAI may never exceed)
# ---------------------------------------------------------------------------
@dataclass
class Citation:
    source_id: str
    quote: str                   # the exact span the principle rests on
    location: str = ""           # timestamp / line / question id


@dataclass
class Principle:
    principle_id: str            # 'P001'
    statement: str               # the validated claim, human-authored
    support: list[Citation] = field(default_factory=list)   # >=1 interview span
    corroborating_surveys: list[Citation] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)            # → Coach retrieval
    status: str = "candidate"    # 'candidate' until a human approves it
    added_by: str = ""
    added_at: str = field(default_factory=_now)

    @property
    def interview_ids(self) -> list[str]:
        return sorted({c.source_id for c in self.support
                       if c.source_id.startswith("I")})

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("interview_ids", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Principle":
        return cls(
            principle_id=d["principle_id"],
            statement=d["statement"],
            support=[Citation(**c) for c in d.get("support", [])],
            corroborating_surveys=[Citation(**c) for c in d.get("corroborating_surveys", [])],
            tags=d.get("tags", []),
            status=d.get("status", "candidate"),
            added_by=d.get("added_by", ""),
            added_at=d.get("added_at", _now()),
        )


# ---------------------------------------------------------------------------
# Layer 2 — generated coaching item (illustrates exactly one principle)
# ---------------------------------------------------------------------------
@dataclass
class Provenance:
    principle_id: str
    interview_ids: list[str] = field(default_factory=list)
    generator_model: str = ""
    prompt_version: str = ""
    generated_at: str = field(default_factory=_now)
    grounding_passed: bool = False
    grounding_notes: str = ""


@dataclass
class Review:
    status: str = STATUS_DRAFT
    reviewer: str = ""
    reviewed_at: str = ""
    notes: str = ""


@dataclass
class GeneratedItem:
    item_id: str                 # 'G0001'
    scenario: str                # a fictional situation illustrating the principle
    signals: list[str] = field(default_factory=list)       # what to notice
    questions: list[str] = field(default_factory=list)     # what to ask
    risks: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)  # other valid readings
    tags: list[str] = field(default_factory=list)
    provenance: Provenance = None                          # set in __post_init__
    review: Review = None

    def __post_init__(self):
        if self.provenance is None:
            self.provenance = Provenance(principle_id="")
        if self.review is None:
            self.review = Review()

    def confidence(self, principle: Principle | None) -> str:
        """Computed, never stored as input. Unverified unless approved AND the
        grounding check passed; otherwise scaled by interview support."""
        if self.review.status != STATUS_APPROVED or not self.provenance.grounding_passed:
            return CONF_UNVERIFIED
        if principle is None:
            return CONF_LOW
        n_interviews = len(principle.interview_ids)
        if n_interviews >= 2:
            return CONF_HIGH
        if n_interviews == 1 and principle.corroborating_surveys:
            return CONF_MEDIUM
        return CONF_LOW

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "scenario": self.scenario,
            "signals": self.signals,
            "questions": self.questions,
            "risks": self.risks,
            "alternatives": self.alternatives,
            "tags": self.tags,
            "provenance": asdict(self.provenance),
            "review": asdict(self.review),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GeneratedItem":
        item = cls(
            item_id=d["item_id"],
            scenario=d.get("scenario", ""),
            signals=d.get("signals", []),
            questions=d.get("questions", []),
            risks=d.get("risks", []),
            alternatives=d.get("alternatives", []),
            tags=d.get("tags", []),
            provenance=Provenance(**d["provenance"]) if d.get("provenance") else None,
            review=Review(**d["review"]) if d.get("review") else None,
        )
        return item
