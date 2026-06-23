"""Central configuration for Senpai.

Holds the model-server connection details (shared with the Phase-1 demo), the
filesystem paths to the seed data, and — most importantly — the *tunable* deal-
health scoring parameters. Everything the scoring engine treats as a threshold
lives here so the rules stay auditable and adjustable in one place (no magic
numbers buried in the engine).

Env:
  BASE_URL      default http://127.0.0.1:8765/v1   (vLLM OpenAI endpoint)
  MODEL         default exp3
  LLM_TIMEOUT   default 120 (seconds) — per-request inference timeout
  LLM_STREAM    default 1 — stream tokens from the server when supported
  LLM_MAX_TOKENS default 1024 — cap on generated tokens for narration
  SENPAI_TODAY  default unset → date.today(); set YYYY-MM-DD to pin the
                "current date" used by scoring (handy for a reproducible demo
                against the committed seed data, whose reference is 2026-06-16).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

def _load_dotenv() -> None:
    """Load .env files into os.environ (stdlib only; never overrides an already-set
    var). config is the first senpai import in every entrypoint, so doing this here
    means BASE_URL/MODEL/etc. take effect everywhere — including the FastAPI bridge.
    Loads the repo-root `.env` first, then `senpai/.env` (handy for keeping
    ingestion keys like OPENAI_BASE_URL/OPENAI_API_KEY next to the package);
    repo-root wins on conflicts because setdefault keeps the first value seen."""
    here = Path(__file__).resolve().parent
    for env in (here.parent / ".env", here / ".env"):
        if not env.exists():
            continue
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

# --- Model server -----------------------------------------------------------
# Any OpenAI-compatible endpoint works here: vLLM (`vllm serve … --port 8765`),
# llama.cpp's `llama-server`, and ollama's `/v1` are all drop-in compatible.
# Only this URL + MODEL change between backends; both come from the repo-root
# .env (loaded above) or process env.
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765/v1")
FALLBACK_BASE_URL = os.environ.get("FALLBACK_BASE_URL", "http://100.101.186.29:8766/v1")
MODEL = os.environ.get("MODEL", "exp3")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "toolmind_exp3_final")
MAX_TOOL_ROUNDS = 4


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Inference tunables -----------------------------------------------------
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 120.0)        # seconds, per request
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 1024)
# Senior Commentary is meant to be a *short* conversational read, not long-form
# reasoning. Cap it tightly so latency stays low (with thinking disabled, wall
# time scales ~linearly with output length on the shared GPU). ~110–150 words.
LLM_NARRATE_MAX_TOKENS = _env_int("LLM_NARRATE_MAX_TOKENS", 300)
LLM_STREAM = os.environ.get("LLM_STREAM", "1").lower() not in ("0", "false", "no", "")

# --- Paths ------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent
SEED_DIR = PKG_DIR / "data" / "seed"
INDEX_DIR = PKG_DIR / "data" / "index"   # committed dense-embedding vectors (build_index.py)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "")


# --- Retrieval (hybrid semantic search) -------------------------------------
# Dense embeddings run on CPU via fastembed (ONNX); corpus vectors are precomputed
# and committed under INDEX_DIR, so only the query is embedded at runtime. Hybrid
# search fuses BM25 + dense via Reciprocal Rank Fusion. Everything degrades to
# BM25 (then keyword) when the libs/vectors are missing — mirrors SENPAI_USE_LLM.
EMBED_MODEL = os.environ.get(
    "SENPAI_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# Dense layer on by default; set SENPAI_USE_EMBEDDINGS=0 for a hermetic BM25-only run
# (tests / no-network CI). semantic.py still no-ops dense if fastembed/vectors absent.
USE_EMBEDDINGS = _env_bool("SENPAI_USE_EMBEDDINGS", True)
USE_RERANKER = _env_bool("SENPAI_USE_RERANKER", False)   # optional cross-encoder, off by default
RRF_K = _env_int("SENPAI_RRF_K", 60)                     # Reciprocal Rank Fusion constant
# Fusion weights — dense carries more weight than lexical BM25 because, on these
# short Japanese notes, the embedding model is the stronger signal for paraphrases.
BM25_WEIGHT = _env_float("SENPAI_BM25_WEIGHT", 1.0)
DENSE_WEIGHT = _env_float("SENPAI_DENSE_WEIGHT", 3.0)

# --- Multimodal ingestion (senpai/ingestion) --------------------------------
# Audio (STT) and image (vision/OCR) run via an OpenAI-compatible *multimodal*
# endpoint — OPENAI_BASE_URL + OPENAI_API_KEY (e.g. Groq's free tier; the local
# exp3 is text-only). Model ids default to Groq's free models; override per env.
INGEST_BASE_URL = os.environ.get("OPENAI_BASE_URL")            # None → api.openai.com
INGEST_API_KEY = os.environ.get("OPENAI_API_KEY")
INGEST_AUDIO_MODEL = os.environ.get("INGEST_AUDIO_MODEL", "whisper-large-v3")
INGEST_VISION_MODEL = os.environ.get(
    "INGEST_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
INGEST_STRUCT_MODEL = os.environ.get(
    "INGEST_STRUCT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


def have_multimodal() -> bool:
    """True when a usable multimodal key is configured (not missing/placeholder)."""
    return bool(INGEST_API_KEY) and INGEST_API_KEY not in ("dummy", "")

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
