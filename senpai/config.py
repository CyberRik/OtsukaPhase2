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
MAX_TOOL_ROUNDS = 15


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
# Senior Commentary budget. Default sized for the fast live path (thinking OFF):
# enough for a flowing conversational read, not long-form. If NARRATE_THINK is
# enabled (reasoning ON, for a pre-warmed cache when the GPU is free), raise this
# to ~2400 so the hidden <think> block plus the answer both fit without truncation.
LLM_NARRATE_MAX_TOKENS = _env_int("LLM_NARRATE_MAX_TOKENS", 600)
# Reasoning on Senior Commentary. OFF by default: on the shared ~11 tok/s box a
# <think> block adds ~2 min/call, too slow for a live demo. Flip on (with a higher
# LLM_NARRATE_MAX_TOKENS) for offline/pre-warmed generation where quality wins.
NARRATE_THINK = os.environ.get("SENPAI_NARRATE_THINK", "0").lower() not in ("0", "false", "no", "")
LLM_STREAM = os.environ.get("LLM_STREAM", "1").lower() not in ("0", "false", "no", "")
# Assistant tool-loop reasoning. Both the tool-selection rounds and the final
# synthesis run the reasoning distill's <think> phase, which dominates Assistant
# latency on the shared ~11 tok/s box. ON skips it (empty-think prefill) across
# the whole loop — same lever the narrate path uses. Measured ~1.9x faster
# overall (up to ~3x on tool + short-answer turns), with tool selection and
# provenance preserved; the only cost seen was an occasional numeric paraphrase
# slip in long answers. Default ON; set SENPAI_TOOLLOOP_NOTHINK=0 to restore the
# slower, fully-reasoned loop.
TOOLLOOP_NO_THINK = os.environ.get("SENPAI_TOOLLOOP_NOTHINK", "1").lower() not in ("0", "false", "no", "")
# Dynamic reasoning router for the Assistant synthesis round (senpai/llm/routing.py).
# "deterministic" (default) routes FAST vs REASONING by the tools used + query
# intent — reasoning is added back only where it helps (numeric/synthesis), while
# retrieval stays fast. "off" reverts to the static TOOLLOOP_NO_THINK behaviour.
# Later: "atlas" / "classifier" / "llm" — swap in get_reasoning_router(), no
# change to the execution loop. Tool-selection rounds are always fast regardless.
REASONING_ROUTER = os.environ.get("SENPAI_REASONING_ROUTER", "deterministic").strip().lower()
# Model decomposition: serve the FAST (no_think) final synthesis from the smaller
# FALLBACK model (8B Q4) instead of the primary 27B — validated ~2.7x faster at
# grounding parity (docs/phase25_session_log.md). THINK synthesis stays on the 27B
# for its mentorship narrative. OFF by default; SENPAI_FAST_SYNTH_FALLBACK=1 routes
# FAST synthesis to the 8B. (Tool selection always stays on the primary 27B.)
FAST_SYNTH_FALLBACK = os.environ.get("SENPAI_FAST_SYNTH_FALLBACK", "0").lower() not in ("0", "false", "no", "")
# Latency-first override: route ALL synthesis (FAST + THINK) to the 8B, not just
# FAST. The 27B THINK synthesis was the slow path (~150s); the 8B does it far
# faster at a quality cost. Implies the fallback endpoint is the 8B.
SYNTH_ALL_FALLBACK = os.environ.get("SENPAI_SYNTH_ALL_8B", "0").lower() not in ("0", "false", "no", "")

# --- Atlas (spark) serving knobs --------------------------------------------
# The served model is now the atlas 35B (Qwen3.6-35B-A3B-NVFP4, spark/atlas on
# :8888). Two atlas-specific behaviours feed every create() call (see
# senpai/llm/client.py::_gen_kwargs):
#   1. Reasoning is toggled via the chat template's `enable_thinking` kwarg
#      (passed through extra_body→chat_template_kwargs), NOT the old empty
#      <think> prefill — atlas ignores the prefill.
#   2. Sampling MUST be set explicitly. With no sampling params atlas decodes
#      greedily and degenerates into repetition loops ("3. 3. 3.") on long
#      output; the recommended Qwen3 non-thinking sampling fixes it.
LLM_TOP_P = _env_float("SENPAI_LLM_TOP_P", 0.95)
LLM_TOP_K = _env_int("SENPAI_LLM_TOP_K", 20)
# Final-answer (synthesis) temperature. Non-zero on purpose: greedy (0.0) long
# generation degenerates on this NVFP4 model. Tool-selection rounds stay greedy
# (short, structured output — no degeneration, more deterministic tool picks).
SYNTH_TEMPERATURE = _env_float("SENPAI_SYNTH_TEMPERATURE", 0.7)

# --- Review Coach grounding controls ----------------------------------------
# Grounding-audit P0: similar past cases are CROSS-CUSTOMER by construction
# (find_similar_cases injects another customer's closed deal ~99% of the time),
# which risks narrative contamination — the model reasoning from analogy rather
# than this customer's own evidence. Disabled by default while we verify grounding.
# Corpus principles (playbooks) are kept; they are a separate, evaluated axis.
COACH_USE_SIMILAR_CASES = os.environ.get("SENPAI_COACH_SIMILAR_CASES", "0").lower() not in ("0", "false", "no", "")
COACH_USE_CORPUS = os.environ.get("SENPAI_COACH_CORPUS", "1").lower() not in ("0", "false", "no", "")

# --- Paths ------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent
SEED_DIR = PKG_DIR / "data" / "seed"
INDEX_DIR = PKG_DIR / "data" / "index"   # committed dense-embedding vectors (build_index.py)
# Committed Segment-Intelligence community reports (build_communities.py). Like the
# dense index, this is a committed build artifact so the runtime is GPU-free — the
# deterministic stats can always be recomputed, and the optional LLM narratives ride
# along. Missing file → senpai.graph.communities rebuilds deterministically in-memory.
COMMUNITIES_PATH = INDEX_DIR / "communities.json"
# A category×industry leaf segment is only emitted as its own report when it has at
# least this many CLOSED deals (won+lost); thinner leaves are represented by their
# parent category rollup, which always aggregates every deal in the category.
SEGMENT_MIN_DEALS = _env_int("SENPAI_SEGMENT_MIN_DEALS", 5)
# Sidecar dir for runtime-ingested rows (daily reports, etc.). Gitignored and
# loaded as an OVERLAY on top of SEED_DIR by senpai.data.store — the committed
# seed stays canonical/byte-stable; ingested data is demo-only and never merged.
INGESTED_DIR = PKG_DIR / "data" / "ingested"
# Output dir for documents the chatbot generates (PPTX proposals, DOCX 稟議書, and
# the general-purpose pptx/docx tools). Gitignored and demo-only, like INGESTED_DIR;
# created on first write. The committed seed is never touched by document generation.
GENERATED_DIR = PKG_DIR / "data" / "generated"

# Cross-chat memory: durable, entity-anchored Observations (the judgments a chat
# reached, NOT transcripts), keyed by Subject so a later chat about the same deal can
# reason from them. Gitignored and demo-only. The JSONL file is a storage STUB behind
# the ObservationStore seam (senpai.orchestration.memory); the persistence layer's DB
# is just another implementation of that interface and replaces this file wholesale.
MEMORY_DIR = PKG_DIR / "data" / "memory"
OBSERVATIONS_PATH = MEMORY_DIR / "observations.jsonl"

# Persistent copilot chat history: durable, per-user conversation transcripts so a
# rep can close the tab and resume a past chat exactly where it left off. A single
# SQLite file (stdlib sqlite3, WAL mode) keyed by conversation_id — deliberately
# SEPARATE from senpai.data.store's seed/overlay tables so chat writes never drop
# store's lru_cache. Gitignored and demo-only, like INGESTED_DIR; created on first
# use. The stored blob is an opaque client-owned transcript the server never parses.
CHAT_DB_PATH = INGESTED_DIR / "chat_history.db"

# --- Workspace (sandboxed local document access) ----------------------------
# The Workspace capability reaches OUTSIDE the seed DB — it finds and reads real
# local documents (PDF/DOCX/PPTX/XLSX/TXT/MD) and returns structured evidence into
# the orchestration EvidenceBundle. It is strictly READ-ONLY and confined to
# WORKSPACE_ROOT: every path is resolved and must stay inside that root (no
# traversal, no symlink escape). Points at a real local docs folder; override with
# SENPAI_WORKSPACE_ROOT. list_documents() prunes VCS/build dirs and our own
# `generated` output so machine artifacts don't feed back in as grounding.
WORKSPACE_ROOT = Path(
    os.environ.get("SENPAI_WORKSPACE_ROOT", r"E:\my_stuff\Otsuka_backup")
).resolve()
# Extensions the Workspace will find/extract (read-only). Lowercase, with dot.
WORKSPACE_EXTS = tuple(
    e.strip().lower() for e in os.environ.get(
        "SENPAI_WORKSPACE_EXTS", ".pdf,.docx,.pptx,.xlsx,.txt,.md").split(",") if e.strip())
# Runtime fan-out cap: a `find` never expands into more than this many parallel
# `extract` tasks, so one query can't read an unbounded tree.
WORKSPACE_MAX_FILES = _env_int("SENPAI_WORKSPACE_MAX_FILES", 12)
# Per-document extracted-text cap (chars) — keeps the evidence bundle bounded and
# the reasoner context safe, mirroring the chat loop's 1500-char tool truncation.
WORKSPACE_MAX_CHARS = _env_int("SENPAI_WORKSPACE_MAX_CHARS", 4000)
# Skip absurdly large files before we even open them (bytes).
WORKSPACE_MAX_BYTES = _env_int("SENPAI_WORKSPACE_MAX_BYTES", 25_000_000)

# Committed brand template for generated PPTX decks: an Otsuka proposal deck with
# all content slides stripped, leaving only its slide masters/layouts/theme (the
# Meiryo UI font + corporate styling). render.render_pptx opens this as the base
# so generated decks inherit Otsuka branding. If absent, rendering falls back to
# python-pptx's blank default (keeps tests/CI green without the committed asset).
PPTX_TEMPLATE_PATH = PKG_DIR / "data" / "templates" / "otsuka_template.pptx"


def fiscal_year_quarter(d_iso: str) -> tuple[int, int]:
    """Japanese fiscal year/quarter for a YYYY-MM-DD date (FY starts in April).
    Single source of truth shared by gen_seed (seed authoring) and ingestion
    (runtime activity records) so both stay in the same fiscal calendar."""
    y, m, _ = (int(x) for x in d_iso.split("-"))
    fy = y if m >= 4 else y - 1
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3,
         1: 4, 2: 4, 3: 4}[m]
    return fy, q


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
