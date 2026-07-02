"""Shared test setup.

Default the suite to **BM25-only** retrieval (no dense embedding model) so the run
stays fast and hermetic — no model download, no network. The dense layer is
exercised explicitly in test_semantic.py only when SENPAI_TEST_DENSE=1. Because
semantic._use_dense() reads config.USE_EMBEDDINGS at call time, flipping the
attribute here is enough.
"""
from __future__ import annotations

import os

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")
os.environ["SENPAI_USE_EMBEDDINGS"] = "0"
# Keep the suite GPU-free and deterministic: default the LLM OFF so tests never hit
# (or depend on the availability of) the served model. `.env` sets SENPAI_USE_LLM=1
# for the app; setdefault here wins for tests unless the runner explicitly exports it
# (opt-in for a live-model check). Must precede `import config` so its .env load —
# which setdefaults SENPAI_USE_LLM from .env — sees this value already set.
os.environ.setdefault("SENPAI_USE_LLM", "0")

from senpai import config  # noqa: E402

config.USE_EMBEDDINGS = False
