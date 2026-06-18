"""Knowledge review console (Streamlit) — the human gate.

A reviewer (senior / trainer) generates draft items from an APPROVED principle,
checks each against its source interview, and approves / asks-for-edit / rejects.
Only approved items ever reach the Sales Review Coach. Provenance and confidence
are shown on every card so the reviewer judges with the citation in front of them.

Run:  .venv/bin/streamlit run senpai/apps/knowledge_review.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from senpai.knowledge import generate, review, store


def main():
    st.set_page_config(page_title="Senpai — Knowledge Review", layout="wide")
    st.title("🗂️ Senpai — Knowledge Review Console")
    st.caption("インタビュー由来の検証済み原則からシナリオを生成し、人手で承認する。"
               "承認されたものだけがコーチに反映されます。")

    reviewer = st.sidebar.text_input("レビュアー名", value="senior_a")
    principles = store.all_principles()
    approved = [p for p in principles if p.status == "approved"]

    st.sidebar.metric("原則(承認済 / 全)", f"{len(approved)} / {len(principles)}")
    if not approved:
        st.warning("承認済みの原則がありません。principles.json で原則を承認し、"
                   "根拠となるインタビュー発言(quote)を実データに置き換えてください。")

    # --- generation -------------------------------------------------------
    st.subheader("1. シナリオ生成（承認済み原則のみ）")
    if approved:
        pid = st.selectbox("原則を選ぶ", [f"{p.principle_id} — {p.statement[:40]}"
                                          for p in approved])
        p = approved[[f"{x.principle_id} — {x.statement[:40]}" for x in approved].index(pid)]
        with st.expander("原則と根拠(出典)を表示", expanded=True):
            st.markdown(f"**{p.statement}**")
            for c in p.support:
                st.markdown(f"> 「{c.quote}」 — `{c.source_id}` {c.location}")
        use_llm = st.toggle("exp3で生成（オフ=オフライン雛形）", value=False)
        if st.button("ドラフトを生成", type="primary"):
            item = generate.generate_item(p, use_llm=use_llm)
            store.save_item(item)
            st.success(f"{item.item_id} を生成（grounding: "
                       f"{'通過' if item.provenance.grounding_passed else '未通過'} — "
                       f"{item.provenance.grounding_notes}）")

    # --- review queue -----------------------------------------------------
    st.subheader("2. レビュー待ち")
    queue = review.pending()
    if not queue:
        st.info("レビュー待ちのドラフトはありません。")
    for it in queue:
        p = store.get_principle(it.provenance.principle_id)
        badge = "✅自動チェック通過" if it.provenance.grounding_passed else "⚠️要確認"
        with st.container(border=True):
            st.markdown(f"**{it.item_id}** · 原則 `{it.provenance.principle_id}` · "
                        f"出典 {('・'.join(it.provenance.interview_ids) or '—')} · "
                        f"確度(承認後) `{it.confidence(p)}` · {badge}")
            if p:
                st.caption(f"原則: {p.statement}")
            st.markdown(f"**シナリオ**: {it.scenario}")
            cols = st.columns(4)
            for col, label, vals in zip(
                cols, ["気づき", "質問", "リスク", "別の見方"],
                [it.signals, it.questions, it.risks, it.alternatives]):
                with col:
                    st.markdown(f"_{label}_")
                    for v in vals:
                        st.markdown(f"- {v}")
            notes = st.text_input("コメント", key=f"n_{it.item_id}")
            b1, b2, b3 = st.columns(3)
            if b1.button("承認", key=f"a_{it.item_id}"):
                review.approve(it.item_id, reviewer, notes); st.rerun()
            if b2.button("修正依頼", key=f"e_{it.item_id}"):
                review.request_edit(it.item_id, reviewer, notes or "要修正"); st.rerun()
            if b3.button("却下", key=f"r_{it.item_id}"):
                review.reject(it.item_id, reviewer, notes); st.rerun()

    # --- approved pool ----------------------------------------------------
    st.subheader("3. 承認済み（コーチに反映）")
    appr = store.approved_items()
    st.metric("承認済みアイテム", len(appr))
    for it in appr:
        p = store.get_principle(it.provenance.principle_id)
        st.markdown(f"- `{it.item_id}` 確度`{it.confidence(p)}` "
                    f"出典{('・'.join(it.provenance.interview_ids) or '—')} — {it.scenario[:60]}")


main()
