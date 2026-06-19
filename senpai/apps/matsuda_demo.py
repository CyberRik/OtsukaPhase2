import streamlit as st
from senpai.matsuda import build_matsuda_context

st.set_page_config(page_title="Matsuda Context Demo", page_icon="🏢", layout="wide")

st.title("Matsuda Context Synthesis Demo")
st.markdown("This is the self-contained, GPU-free context synthesizer for the Matsuda account. It reads purely from the data store and handles Q&A locally without touching other workflows.")

@st.cache_resource
def get_ctx():
    return build_matsuda_context("C28")

ctx = get_ctx()

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Questions to ask:")
    questions = [
        "Tell me about Matsuda",
        "What are the biggest risks?",
        "Who is the decision maker?",
        "When was the last meeting?",
        "What products are they interested in?",
        "What should I do next?",
        "Tell me about their IT environment",
        "How is the health of the deals?",
        "Who owns these deals?",
        "What is the total pipeline value?"
    ]
    for q in questions:
        st.write(f"- {q}")

with col2:
    st.subheader("Interactive Q&A")
    query = st.text_input("Ask a question about Matsuda:", "Tell me about Matsuda")
    if query:
        with st.chat_message("user"):
            st.write(query)
        with st.chat_message("assistant"):
            st.write(ctx.answer(query))

st.divider()
with st.expander("View Full Synthesized Markdown Report"):
    st.markdown(ctx.to_markdown())
