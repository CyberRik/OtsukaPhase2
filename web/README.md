# Senpai — Web frontend

Production-quality Next.js frontend that presents Senpai as a **knowledge-transfer
and onboarding platform** for salespeople. It talks to a thin FastAPI bridge
(`senpai/api/server.py`) that wraps the existing engines unchanged.

```
Next.js (web/)  ──HTTP──▶  FastAPI bridge (senpai/api)  ──calls──▶  existing engines
                                                                    (scoring, coach, knowledge)
```

If the API is offline the UI degrades to a committed seed snapshot
(`lib/fixtures.ts`) and labels itself "Seed snapshot" — it never shows a broken
screen.

## Run (two terminals)

**1 — the API bridge** (from repo root):

```bash
pip install -r senpai/api/requirements.txt   # fastapi + uvicorn (kept separate from gradio)
SENPAI_TODAY=2026-06-16 uvicorn senpai.api.server:app --port 8000
```

**2 — the frontend** (from `web/`):

```bash
npm install
cp .env.example .env.local      # optional; default points at localhost:8000
npm run dev                     # http://localhost:3000
```

On Windows PowerShell the API line is:

```powershell
$env:SENPAI_TODAY="2026-06-16"; uvicorn senpai.api.server:app --port 8000
```

## Pages

| Route | Purpose |
|---|---|
| `/` | What Senpai is — the three-layer trust model, stats, surfaces. |
| `/coach` | Sales Review Coach — paste a note → six lenses of senior reasoning. |
| `/knowledge` | Knowledge Explorer — principles, verbatim provenance, derived items. |
| `/dashboard` | Manager Dashboard — deal-health, reliability flags, drill-down. |

## Stack

Next.js 15 (App Router) · TypeScript · Tailwind 3 · shadcn/ui primitives (Radix)
· lucide-react. Fonts: Spectral (serif display), Inter (sans), Noto Sans JP.

See `DESIGN.md` for the full design system and per-page specification.
