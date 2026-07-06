"""Recommendation schema."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Recommendation:
    solution_name: str
    category: str
    match_score: float
    confidence: float
    why: str
    evidence: tuple[str, ...]
    product_pages: tuple[dict, ...]
    business_value: str
    risks: tuple[str, ...]
    complementary_solutions: tuple[str, ...]
    status: str = "recommended"  # "recommended" | "already_owned" | "watch"

    def as_dict(self) -> dict:
        return {
            "solution_name": self.solution_name,
            "category": self.category,
            "match_score": self.match_score,
            "confidence": self.confidence,
            "why": self.why,
            "evidence": list(self.evidence),
            "product_pages": list(self.product_pages),
            "business_value": self.business_value,
            "risks": list(self.risks),
            "complementary_solutions": list(self.complementary_solutions),
            "status": self.status,
        }
