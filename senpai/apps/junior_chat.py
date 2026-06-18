"""Junior assistant (Gradio) — a sales 'senpai' in chat form.

Ports demo/app.py's UI (chatbot + collapsible 'tools used' panel + examples) and
points it at Senpai's sales tools. Grounds every answer in Otsuka data, cites
playbook sources, and routes to an expert when confidence is low.

Run:
  1. scripts/serve_model.sh                  # exp3 on :8765 (needs GPU)
  2. .venv/bin/python senpai/apps/junior_chat.py   # opens UI on :7860
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

# Run directly (`python senpai/apps/junior_chat.py`), so the repo root isn't on
# sys.path by default — add it so `import senpai` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import gradio as gr

from senpai import config
from senpai.llm.client import stream_turn
from senpai.tools.schemas import JUNIOR_TOOLS

SYSTEM_PROMPT = (
    "あなたは大塚商会の新人営業を支える『先輩(senpai)』アシスタントです。"
    "回答は必ず社内データ(SPR・プレイブック・顧客環境・案件健全度)に基づき、"
    "ツールを使って事実を確認してから答えてください。プレイブックを引用する際は"
    "提供者名を添えること。自信が持てない時は route_to_expert で適切な先輩に橋渡し"
    "してください。新人がメモや日報を共有してきたら review_sales_note で振り返りを"
    "コーチングし、正解を一つ押し付けず『先輩なら何に気づくか』を示してください。"
    "日本語で、簡潔かつ実務的に答えます。"
    f"本日は {date.today().isoformat()} です。"
)

EXAMPLES = [
    "明日アクメ商事に訪問。準備をお願い",
    "D001の案件、これは本当に進んでる？健全度を見て",
    "お客様が決定を先延ばしにします。先輩ならどうしますか？",
    "この日報を見て先輩ならどう考える？：お客様は社内で検討してから連絡するとのこと",
    "今日の活動から日報を作成して：村田印刷を訪問し複合機のデモを実施",
    "ネットワーク更改の構成、誰に相談すればいい？",
    "製造業の最近のIT動向を調べて",
]


def _fmt_args(arguments) -> str:
    import json
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return ", ".join(f"{k}={v!r}" for k, v in d.items())
    except Exception:
        return str(arguments)


def respond(user_msg: str, display: list, convo: list):
    """One user turn; yields a natural-language answer plus a collapsible panel
    of the tools that produced it (ported from demo/app.py)."""
    user_msg = (user_msg or "").strip()
    display = list(display or [])
    if not user_msg:
        yield display, convo, ""
        return

    if not convo:
        convo = [{"role": "system", "content": SYSTEM_PROMPT}]
    convo.append({"role": "user", "content": user_msg})
    display = display + [{"role": "user", "content": user_msg}]
    status = {"role": "assistant", "content": "_ツールを実行中…_",
              "metadata": {"title": "⏳ Working", "status": "pending"}}
    yield display + [status], convo, ""

    tool_log, answer = [], None
    for tool_log, answer in stream_turn(convo, tools=JUNIOR_TOOLS):
        if answer is None:
            running = "\n".join(f"• `{n}({a})`" for n, a, _ in tool_log)
            status = {"role": "assistant", "content": running,
                      "metadata": {"title": f"🔧 Ran {len(tool_log)} tool(s)…",
                                   "status": "pending"}}
            yield display + [status], convo, ""

    msgs = display + [{"role": "assistant", "content": answer}]
    if tool_log:
        detail = "\n\n".join(f"**{i}. `{n}({a})`**\n\n→ {r}"
                             for i, (n, a, r) in enumerate(tool_log, 1))
        msgs.append({"role": "assistant", "content": detail,
                     "metadata": {"title": f"🔧 {len(tool_log)} tool call(s) — show details"}})
    yield msgs, convo, ""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Senpai — Junior Sales Assistant", fill_height=True) as ui:
        gr.Markdown(f"## 🧑‍🏫 Senpai — junior sales assistant — `{config.MODEL}`\n"
                    "自然な日本語で質問してください。社内データに基づき、先輩の知見と"
                    "案件の健全度をその場で返します。各回答の下の **tool call(s)** を"
                    "開くと、実際に呼び出したツールが確認できます。")
        chatbot = gr.Chatbot(value=[], height=460, show_label=False)
        convo = gr.State([])
        with gr.Row():
            box = gr.Textbox(placeholder="例: 明日アクメ商事に訪問。準備をお願い",
                             scale=8, show_label=False, autofocus=True)
            send = gr.Button("送信", variant="primary", scale=1)
        gr.Examples(EXAMPLES, inputs=box, label="例を試す")
        clear = gr.Button("クリア")

        send.click(respond, [box, chatbot, convo], [chatbot, convo, box])
        box.submit(respond, [box, chatbot, convo], [chatbot, convo, box])
        clear.click(lambda: ([], [], ""), None, [chatbot, convo, box])
    return ui


if __name__ == "__main__":
    build_ui().launch(
        server_name=os.environ.get("UI_HOST", "127.0.0.1"),
        server_port=int(os.environ.get("UI_PORT", 7860)),
    )
