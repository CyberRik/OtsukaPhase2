# Web ↔ engine integration

The Python engine and the Next.js app are **one stack**, not two backends. The web app
has no backend logic of its own — it reads everything through one HTTP boundary.

## The boundary

```
senpai/ engines  →  senpai/api/server.py  →  web/lib/api.ts   →  React components
(scoring, coach,    (FastAPI bridge,         (typed client,       (web/app, web/components)
 knowledge, …)       JSON + SSE, :8000)       fetches :8000)
                                              └ web/lib/types.ts   (the shapes)
                                              └ web/lib/fixtures.ts (offline fallback)
```

- `senpai/api/server.py` is the **only** thing the frontend talks to. It wraps the engines
  unchanged and returns JSON (or SSE for chat/narration).
- `web/lib/api.ts` is the **only** place the frontend issues requests. Components never fetch
  directly.
- `web/lib/types.ts` declares the response shapes; `web/lib/fixtures.ts` holds a committed
  snapshot returned (with `live:false`) when the API is unreachable, so demos never break.

## The rule: endpoint first, then types/api/fixture

When you add or change an engine feature that the UI should show:

1. Expose it as an endpoint in `senpai/api/server.py`.
2. Add/adjust its shape in `web/lib/types.ts`.
3. Add/adjust the method in `web/lib/api.ts` (with a fallback value).
4. Add/refresh the matching entry in `web/lib/fixtures.ts`.
5. Then build the component.

No web feature reads data any other way. This keeps the two halves from drifting as you and
your teammate work in parallel.

## Running the integrated stack

```bash
scripts/run_web.sh          # FastAPI bridge (:8000) + Next.js dev server (:3000), Ctrl-C stops both
```

Requires Python deps installed and `npm install` already run in `web/`. The LLM/SSE endpoints
degrade gracefully if the GPU model server (`scripts/serve_model.sh`, :8765) isn't running.

## Catching drift

```bash
SENPAI_TODAY=2026-06-16 python scripts/check_contract.py   # asserts every web-consumed GET endpoint's keys
cd web && npm run typecheck                                # asserts the TS shapes compile
```

`scripts/check_contract.py` runs in-process (FastAPI `TestClient`, no server/GPU needed) and
exits non-zero if any `/api/*` response stops returning a key the web client expects. Run both
after touching `server.py` or `web/lib/{types,api}.ts`.
