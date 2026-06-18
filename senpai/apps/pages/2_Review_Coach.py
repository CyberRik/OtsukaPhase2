"""Multipage wrapper → review_coach.py (GPU-free)."""
import os
import runpy
import sys
from pathlib import Path

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")
APPS = Path(__file__).resolve().parents[1]        # senpai/apps
sys.path.insert(0, str(APPS.parents[1]))           # repo root → import senpai

runpy.run_path(str(APPS / "review_coach.py"), run_name="__main__")
