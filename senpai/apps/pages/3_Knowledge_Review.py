"""Multipage wrapper → knowledge_review.py (GPU-free).

Approvals here write to the container filesystem, which Streamlit Cloud resets on
reboot/redeploy. For the demo that's fine; to persist, approve locally and commit
senpai/knowledge/seed/*.json.
"""
import os
import runpy
import sys
from pathlib import Path

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")
APPS = Path(__file__).resolve().parents[1]        # senpai/apps
sys.path.insert(0, str(APPS.parents[1]))           # repo root → import senpai

runpy.run_path(str(APPS / "knowledge_review.py"), run_name="__main__")
