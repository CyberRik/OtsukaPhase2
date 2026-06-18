"""Manager dashboard (Streamlit) — team pipeline health & report reliability.

Pure-Python: loads and scores entirely from the deterministic engine, so it runs
with NO model server. exp3 is used only to narrate a selected deal's flag, and
that call degrades to a templated string when the server is down.

Run:  .venv/bin/streamlit run senpai/apps/manager_dashboard.py
UI chrome is English; the data content stays Japanese (bilingual by design).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this file directly, so the repo root isn't on sys.path by
# default — add it so `import senpai` resolves (apps → senpai → repo root).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from senpai import config
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal

_CHIP = {"red": "🔴", "yellow": "🟡", "green": "🟢"}


def _last_activity_date(acts):
    dates = [a.get("activity_date") for a in acts if a.get("activity_date")]
    return max(dates) if dates else None


@st.cache_data
def _scored_rows():
    """Score every open deal once. Returns (rows, flagged_reports)."""
    rows, flagged = [], []
    today = config.today()
    for d in store.open_deals():
        acts = store.activities_for_deal(d["deal_id"])
        res = score_deal(d, acts, today=today)
        flags = deal_flags(d, acts, res.band, today=today)
        rep = store.rep_name(store.deal_rep_id(d))
        last = _last_activity_date(acts)
        stale_days = (today - pd.to_datetime(last).date()).days if last else None
        regressed = config.rank_num(d["order_rank"]) > config.rank_num(d.get("initial_order_rank"))
        rows.append({
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
            "rep": rep,
            "rank": d["order_rank"],
            "amount": d["total_order_amount"],
            "health": _CHIP[res.band],
            "band": res.band,
            "score": res.score,
            "days_stale": stale_days,
            "order_date": d["expected_order_date"],
            "regressed": "↓" if regressed else "",
            "n_flags": len(flags),
        })
        for f in flags:
            flagged.append({
                "deal_id": d["deal_id"],
                "customer": store.customer_name(d["customer_id"]),
                "rep": rep,
                "severity": f.severity,
                "flag": f.name,
                "message": f.message,
            })
    return rows, flagged


def main():
    st.set_page_config(page_title="Senpai — Deal Health Dashboard", layout="wide")
    st.title("📊 Senpai — Team Deal-Health Dashboard")
    st.caption("Deterministic scoring · no GPU required · the same engine powers the "
               "junior's pre-call brief in the chat assistant.")

    rows, flagged = _scored_rows()
    df = pd.DataFrame(rows)

    # --- filters ---
    reps = ["(all)"] + sorted(df["rep"].unique().tolist())
    pick_rep = st.sidebar.selectbox("Filter by rep", reps)
    if pick_rep != "(all)":
        df = df[df["rep"] == pick_rep]
        flagged = [f for f in flagged if f["rep"] == pick_rep]

    # --- KPI row ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open deals", len(df))
    c2.metric("🔴 At-risk", int((df["band"] == "red").sum()))
    c3.metric("Flagged reports", len(flagged))
    c4.metric("Pipeline ¥", f"¥{int(df['amount'].sum()):,}")

    st.subheader("Team pipeline")
    view = df[["deal_id", "customer", "rep", "rank", "amount", "health",
               "score", "days_stale", "order_date", "regressed", "n_flags"]]
    st.dataframe(view, use_container_width=True, hide_index=True)

    # --- drill-down ---
    st.subheader("Deal drill-down")
    deal_id = st.selectbox("Select a deal", df["deal_id"].tolist())
    if deal_id:
        _render_deal(deal_id)

    # --- reliability panel ---
    st.subheader("⚠️ Report-reliability flags")
    if flagged:
        order = {"high": 0, "medium": 1, "low": 2}
        fdf = pd.DataFrame(sorted(flagged, key=lambda r: order.get(r["severity"], 3)))
        st.dataframe(fdf, use_container_width=True, hide_index=True)
    else:
        st.success("No reliability flags for this selection.")


def _render_deal(deal_id: str):
    d = store.get_deal(deal_id)
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts)
    flags = deal_flags(d, acts, res.band)

    left, right = st.columns([2, 3])
    with left:
        st.markdown(f"**{store.customer_name(d['customer_id'])}** — "
                    f"{store.rep_name(store.deal_rep_id(d))}")
        st.markdown(f"{_CHIP[res.band]} **{res.band.upper()}** · risk {res.score}/100 · "
                    f"rank {d['order_rank']} (initial {d.get('initial_order_rank')})")
        st.markdown("**Signal breakdown**")
        for s in sorted(res.signals, key=lambda x: x.points, reverse=True):
            st.markdown(f"- `+{s.points}` {s.reason}")
        if not res.signals:
            st.markdown("- _no risk signals_")

    with right:
        use_llm = st.toggle("Narrate with exp3 (off = templated)", value=False,
                            help="Requires the vLLM server; off uses the deterministic fallback.")
        # Imported lazily so the dashboard loads even if openai isn't installed.
        from senpai.llm.narrate import narrate_deal
        st.markdown("**Manager flag & suggested action**")
        st.info(narrate_deal(d, res, flags, use_llm=use_llm))
        st.markdown("**Recent activities**")
        for a in acts[:3]:
            st.markdown(f"- {a['activity_date']} [{a['activity_type']}] {a['daily_report']}")


main()
