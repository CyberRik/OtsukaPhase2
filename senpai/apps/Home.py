"""Streamlit Cloud entry point — Senpai (GPU-free apps only).

Deploy this file as the main module. Streamlit auto-discovers the sibling
`pages/` folder into the sidebar:

  📊 Deal Health      — team pipeline, red/yellow/green, reliability flags
  🧑‍🏫 Review Coach     — paste a note → a senior's reasoning scaffold
  🗂️ Knowledge Review — approve interview-derived principles → coaching items

The two Gradio chats are NOT here: they need the exp3 vLLM server (GPU), which
Community Cloud can't host. Everything on this deployment is pure-Python and runs
without a model server (exp3 narration is optional and degrades gracefully).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Pin scoring's "today" to the committed seed anchor so deal bands are identical
# regardless of the real date the demo is viewed. Override in Streamlit secrets.
os.environ.setdefault("SENPAI_TODAY", "2026-06-16")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root → import senpai

import streamlit as st

st.set_page_config(page_title="Senpai", page_icon="🧑‍🏫", layout="wide")

st.title("🧑‍🏫 Senpai — Sales Knowledge & Deal-Health Copilot")
st.caption("Phase 2 internship prototype · deterministic core · GPU-free demo")

st.markdown(
    """
Use the sidebar to open a tool:

| Tool | What it does |
|---|---|
| **📊 Deal Health** | The team pipeline with red/yellow/green deal health and report-reliability flags. Drill into any deal for the signal-by-signal breakdown. |
| **🧑‍🏫 Review Coach** | Paste a meeting note / daily report and get a senior rep's reasoning scaffold — what they'd notice, what's missing, the questions they'd ask, and **several** possible next moves. It teaches reasoning, never one "right answer." |
| **🗂️ Knowledge Review** | The human gate: generate coaching scenarios from interview-derived principles and approve them. Approved, source-traceable advice is what the Coach surfaces. |

**No synthetic expertise:** the Coach only shows human-approved knowledge that
traces back to a real interview sentence, with a computed confidence level.

> The two Gradio chat assistants (junior / manager) aren't on this deployment —
> they require the exp3 GPU model server. Run them locally; see `README_senpai.md`.
"""
)

st.info("This demo's deal data is synthetic and bilingual (Japanese content). "
        "The interview knowledge in Knowledge Review is real and fully cited.")
