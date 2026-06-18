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


# --- Order-rank model (mirrors the production `deals.order_rank` values) -----
# The real SPR schema ranks every deal on this 8-point scale. We treat ranks 2–6
# as the live pipeline, 1 as won, and 7–8 as dead. Lower prefix number = stronger
# (closer to a confirmed order).
ORDER_RANKS = ["1_Confirmed", "2_A+", "3_A", "4_B", "5_C", "6_P", "7_Lost", "8_Cancelled"]
OPEN_RANKS = {"2_A+", "3_A", "4_B", "5_C", "6_P"}   # live pipeline
WON_RANKS = {"1_Confirmed"}
DEAD_RANKS = {"7_Lost", "8_Cancelled"}


def rank_num(order_rank: str | None) -> int:
    """Numeric prefix of an order_rank ('3_A' → 3); unknown/NULL → 99."""
    try:
        return int(str(order_rank).split("_", 1)[0])
    except (ValueError, AttributeError):
        return 99


def is_open_rank(order_rank: str | None) -> bool:
    return order_rank in OPEN_RANKS


# --- Deal-health scoring parameters (all tunable) ---------------------------
# Per-rank health benchmarks: (max healthy days at this rank, expected contact
# cadence in days). A deal sitting longer than the benchmark accrues risk points.
RANK_BENCHMARKS: dict[str, tuple[int, int]] = {
    "2_A+": (21, 7),
    "3_A":  (30, 10),
    "4_B":  (45, 14),
    "5_C":  (60, 21),
    "6_P":  (60, 21),
}

# Ranks strong enough that a decision-maker really should be identified by now.
DECISION_MAKER_RANKS = {"2_A+", "3_A", "4_B"}

# Titles in sales_activities.business_card_info that count as a decision-maker contact.
DECISION_MAKER_TITLES = ["社長", "代表", "取締役", "役員", "本部長", "部長", "課長",
                         "責任者", "マネージャー", "CIO", "情シス長"]

# Ranks the rep is signalling as likely to close — used for the optimism-mismatch
# reliability flag (strong rank but red health = report doesn't match reality).
OPTIMISTIC_RANKS = {"2_A+", "3_A"}

# Japanese stall lexicon — phrases that, in the latest daily_report, signal a stall.
STALL_LEXICON = ["検討します", "予算が", "時期を見て", "上と相談", "持ち帰り", "また連絡"]

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
