"""Central configuration for Senpai.

Holds the model-server connection details (shared with the Phase-1 demo), the
filesystem paths to the seed data, and — most importantly — the *tunable* deal-
health scoring parameters. Everything the scoring engine treats as a threshold
lives here so the rules stay auditable and adjustable in one place (no magic
numbers buried in the engine).

Env:
  BASE_URL      default http://127.0.0.1:8765/v1   (vLLM OpenAI endpoint)
  MODEL         default exp3
  SENPAI_TODAY  default unset → date.today(); set YYYY-MM-DD to pin the
                "current date" used by scoring (handy for a reproducible demo
                against the committed seed data, whose reference is 2026-06-16).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

# --- Model server (shared with demo/) ---------------------------------------
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765/v1")
MODEL = os.environ.get("MODEL", "exp3")
MAX_TOOL_ROUNDS = 4

# --- Paths ------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent
SEED_DIR = PKG_DIR / "data" / "seed"

# Fixed anchor used by data/gen_seed.py so the committed seed JSON is byte-stable
# no matter what day it is regenerated. Scoring uses today() (below), which on the
# authoring date equals this anchor.
REFERENCE_DATE = date(2026, 6, 16)


def today() -> date:
    """The 'current date' scoring reasons against. Override with SENPAI_TODAY
    for a perfectly reproducible demo against the committed seed."""
    raw = os.environ.get("SENPAI_TODAY")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


# --- Deal-health scoring parameters (all tunable) ---------------------------
# Per-stage health benchmarks: (max healthy days-in-stage, expected contact
# cadence in days). Stages beyond these start accruing risk points.
STAGE_BENCHMARKS: dict[str, tuple[int, int]] = {
    "lead": (14, 7),
    "qualified": (21, 10),
    "proposal": (30, 14),
    "negotiation": (30, 10),
    "closing": (21, 7),
}

# Stages at which a decision-maker really should be identified.
DECISION_MAKER_STAGES = {"proposal", "negotiation", "closing"}

# Japanese stall lexicon — phrases that, in the latest note, signal a stalling deal.
STALL_LEXICON = ["検討します", "予算が", "時期を見て", "上と相談", "持ち帰り", "また連絡"]

# Words that, when present in a note, mean a competitor is in play (a *factor* the
# rep should reason about, not a gap). Used by the Sales Review Coach.
COMPETITION_LEXICON = ["競合", "他社", "相見積", "コンペ", "比較中", "比較検討"]

# Risk-score band thresholds (score is 0–100, higher = worse).
RED_THRESHOLD = 55      # score >= 55  → red
YELLOW_THRESHOLD = 25   # 25 <= score < 55 → yellow ; < 25 → green


def band_for_score(score: int) -> str:
    """Map a 0–100 risk score to a traffic-light band."""
    if score >= RED_THRESHOLD:
        return "red"
    if score >= YELLOW_THRESHOLD:
        return "yellow"
    return "green"
