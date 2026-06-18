"""Sales Review Coach (Streamlit) — paste a note, see a senior's reasoning.

The onboarding surface: a junior pastes a meeting note or daily report and gets a
senior rep's mental checklist made explicit — what they'd notice, what's missing,
what they'd ask, and several plausible next moves (never one 'right answer').

Pure-deterministic by default (no model server, no GPU). Toggle exp3 narration on
to have the same findings rephrased in a teaching tone; it falls back silently if
the server is down.

Run:  .venv/bin/streamlit run senpai/apps/review_coach.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from senpai.coach.review import narrate_review, review_note
from senpai.data import store

_EXAMPLE = "お客様は社内で検討してから連絡するとのこと。前向きな反応だった。"

_SECTIONS = [
    ("observations",     "🔎 経験豊富な営業が気づくこと"),
    ("missing_info",     "❓ 確認できていない情報"),
    ("risks",            "⚠️ リスクの兆候"),
    ("questions",        "💬 次に聞くとよい質問"),
    ("next_actions",     "➡️ 取りうる次の一手（状況により選ぶ）"),
    ("decision_factors", "⚖️ 判断に影響する要因"),
]


def main():
    st.set_page_config(page_title="Senpai — Sales Review Coach", layout="wide")
    st.title("🧑‍🏫 Senpai — Sales Review Coach")
    st.caption("メモや日報を貼り付けると、先輩なら何に気づくかを返します。"
               "正解を一つ示すのではなく、考え方の型を学ぶためのものです。")

    deal_ids = ["(なし)"] + [d["deal_id"] for d in store.all_deals()]
    c1, c2 = st.columns([3, 1])
    with c1:
        note = st.text_area("メモ・日報", value=_EXAMPLE, height=140)
    with c2:
        deal_id = st.selectbox("関連案件 (任意)", deal_ids,
                               help="選ぶと案件データの信号も反映されます")
        use_llm = st.toggle("exp3で言い換える", value=False,
                            help="オフでも完全に動作します(決定論的)")
        go = st.button("レビュー", type="primary", use_container_width=True)

    if not go:
        return

    did = "" if deal_id == "(なし)" else deal_id
    deal = store.get_deal(did) if did else None
    notes = store.notes_for_deal(did) if deal else None
    report = store.report_for_deal(did) if deal else None
    review = review_note(note, deal=deal, notes=notes, report=report)

    st.info("※ 正解を一つ示すものではありません。状況に応じて自分で選んでください。")
    if use_llm:
        st.markdown(narrate_review(review, use_llm=True))
        with st.expander("決定論的な分析（元データ）"):
            _render_sections(review)
    else:
        _render_sections(review)


def _render_sections(review):
    cols = st.columns(2)
    for i, (field_name, title) in enumerate(_SECTIONS):
        items = getattr(review, field_name)
        with cols[i % 2]:
            st.markdown(f"**{title}**")
            if items:
                for it in items:
                    st.markdown(f"- {it}")
            else:
                st.markdown("- _該当なし_")


main()
