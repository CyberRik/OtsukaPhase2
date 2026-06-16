# OtsukaPhase2

Live demo of the **ToolCallLM (exp3)** model: a small Gradio chatbot that answers
in natural language while calling real tools (product catalog, quoting, weather,
currency, web search, file writing, and Google Calendar booking) behind the scenes.

It runs as **two processes**: a vLLM server that hosts the model, and a Gradio UI
that talks to it over an OpenAI-compatible API.

```
demo/app.py    ──HTTP /v1──▶  vLLM server (serve_demo.sh)  ──▶  merged exp3 model
   │  Gradio UI on :7860          on :8765                       (16 GB weights)
   └─ demo/tools.py  (tool implementations)
   └─ demo/gcal.py   (real Google Calendar booking)
```

## Prerequisites

- A free GPU (the model is ~16 GB).
- **The model weights and the vLLM serving environment live outside this repo**, in
  the original `ToolCallLM_finetune` project:
  - venv (has vLLM + CUDA): `/home/team-a/Desktop/ToolCallLM_finetune/.venv`
  - model: `…/ToolCallLM/outputs/merged_toolmind_exp3_final`

  `demo/serve_demo.sh` points at both by absolute path and fails with a clear
  message if either is missing. Override with `MODEL=` / `VENV=` if they move.

## Setup

```bash
# 1. UI dependencies — into this project's venv
.venv/bin/pip install -r requirements.txt
```

The serving side (vLLM) uses the external venv above; nothing to install there.

### Optional real-tool keys

- **Web search (Tavily):** put `TAVILY_API_KEY=...` in a repo-root `.env`
  (loaded automatically by `demo/tools.py`). Without it, `web_search` falls back
  to canned results.
- **Google Calendar:** `schedule_meeting` books a real event.
  1. Google Cloud Console → enable the **Google Calendar API**.
  2. Create an **OAuth client ID → Desktop app**, download the JSON, and save it as
     `demo/credentials.json` (use `demo/credentials.json.example` as a template).
  3. Add your Google account as a **test user** on the consent screen.
  4. The first booking opens a browser consent once and writes `demo/token.json`.

  Without these, `schedule_meeting` degrades to a `(simulated)` confirmation, so the
  demo never breaks.

## Run

```bash
# Terminal A — serve the model (waits for the GPU)
./demo/serve_demo.sh                 # exp3 on http://127.0.0.1:8765

# Terminal B — launch the UI
.venv/bin/python demo/app.py         # open http://localhost:7860
```

Sanity check the server before recording:

```bash
curl -s localhost:8765/v1/models | python3 -m json.tool   # should list "exp3"
```

See [`demo/demo_script.md`](demo/demo_script.md) for the full run sheet, example
prompts, and talking points.

## Environment variables

| Var | Default | Used by | Meaning |
|-----|---------|---------|---------|
| `MODEL` | external model path | `serve_demo.sh` | Model dir to serve |
| `VENV` | external venv path | `serve_demo.sh` | venv with vLLM |
| `PORT` | `8765` | `serve_demo.sh` | vLLM server port |
| `BASE_URL` | `http://127.0.0.1:8765/v1` | `app.py` | Where the UI sends requests |
| `MODEL` | `exp3` | `app.py` | Served-model name (must match `--served-model-name`) |
| `UI_HOST` | `127.0.0.1` | `app.py` | Bind address (use `0.0.0.0` to expose) |
| `UI_PORT` | `7860` | `app.py` | UI port |
| `TAVILY_API_KEY` | — | `tools.py` | Enables real web search |

## Security

`demo/credentials.json` and `demo/token.json` hold OAuth secrets and are
git-ignored — never commit them. If they were ever committed, rotate the OAuth
client secret and revoke the token.
