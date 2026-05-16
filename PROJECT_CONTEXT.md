# Project Context — AI Execution Command Center

> One-stop orientation doc for anyone (or any agent) adding features to this workspace.
> Companion docs: [ARCHITECTURE.md](ARCHITECTURE.md), [TESTING.md](TESTING.md), [FEATURES.md](FEATURES.md).

---

## 1. What this project is

A two-app demo that turns a workplace meeting into structured, dispatched follow-up work and live execution KPIs.

| App | Folder | Port | Role |
|---|---|---|---|
| **Meeting Master** | [meeting-master/](meeting-master/) | `5098` | Captures meetings (audio or text), extracts tasks/summary/MoM, computes KPIs, auto-dispatches email + calendar. |
| **RequireWise (BRD Agent)** | [brd-agent/](brd-agent/) | `8025` | Turns meeting context into BRDs and renders the cross-app execution dashboard. |
| **Scripts** | [scripts/](scripts/) | — | Install / start / stop / e2e-validate on Windows + PowerShell. |

Both apps are FastAPI + plain HTML/JS frontends, run via `uvicorn`. State is JSON-on-disk (no DB).

## 2. Demo narrative (KPI story)

The story for judges, from [README.md](README.md):

- **Execution Health Index (EHI)** — how ready a meeting is for actual execution
- **Context Completeness Score** — meeting output clear enough to act on without rework
- **Action Leakage Rate** — commitments spoken but never converted into structured follow-up
- **Automation Coverage** — how often the system closes the loop via email/calendar dispatch

KPI math lives in [meeting-master/backend/services/kpi.py](meeting-master/backend/services/kpi.py) (`compute_meeting_kpis`, `compute_portfolio_kpis`).

## 3. Tech stack

- **Backend:** Python 3.11, FastAPI, uvicorn, Pydantic. AI calls via `openai`, `anthropic`, `google-generativeai`, OpenRouter. Transcription via Deepgram / Groq / Sarvam.
- **Frontend:** Vanilla HTML/CSS/JS. PWA bits in `meeting-master/frontend` (`manifest.json`, `sw.js`).
- **Storage:** JSON files. Meeting Master uses `meeting-master/data/store.json`; uploads in `meeting-master/data/uploads/`.
- **External pipelines:** Optional n8n webhooks (`USE_N8N_WEBHOOKS=true` by default) for transcription, summarization, Google Tools, email send — see [meeting-master/backend/config.py](meeting-master/backend/config.py).
- **Auth:** Descope JWT in production; guest-JWT (`python-jose`) locally. `AUTH_DISABLED=true` is set by [scripts/start-demo.ps1](scripts/start-demo.ps1) so local probing doesn't need a token.

## 4. Repo layout (top of mind)

```
10xHackathon/
├─ README.md                        ← run instructions
├─ PROJECT_CONTEXT.md               ← this file
├─ ARCHITECTURE.md                  ← services + endpoints + data flow
├─ TESTING.md                       ← how to test, last result
├─ FEATURES.md                      ← what exists, where to extend
├─ scripts/
│  ├─ setup-demo.ps1                ← pip install both apps
│  ├─ start-demo.ps1                ← spawn both uvicorn servers
│  ├─ stop-demo.ps1                 ← kill them
│  └─ test-e2e.ps1                  ← 13-check black-box e2e
├─ meeting-master/
│  ├─ backend/
│  │  ├─ api.py                     ← all FastAPI routes (~2500 lines)
│  │  ├─ auth.py, config.py, models.py
│  │  └─ services/  (ai, kpi, storage, webhook)
│  ├─ frontend/  (index.html, app.js, styles.css, sw.js)
│  ├─ data/      (store.json, uploads/)
│  └─ docker/    (requirements.txt — canonical deps)
├─ brd-agent/
│  ├─ backend/
│  │  ├─ server.py                  ← FastAPI routes + BRD logic (~900 lines)
│  │  ├─ config.json                ← project list seed
│  │  └─ requirements.txt
│  └─ frontend/  (index.html, script.js, dashboard.js, styles.css)
└─ .github/skills/                  ← internal "skills" docs for the demo flow
```

## 5. How they talk to each other

- Browser (RequireWise) → `POST /api/dashboard-data` on brd-agent (`:8025`)
- brd-agent → `GET /api/v1/kpis/business-overview` on meeting-master (`:5098`), via env `MEETING_MASTER_API_BASE`
- Meeting Master → optional **n8n webhooks** for transcribe / summarize / google-tools / send-email. Falls back locally on webhook failure (see [README.md](README.md) and [meeting-master/backend/services/webhook.py](meeting-master/backend/services/webhook.py)).
- BRD generation: `POST /api/v1/meetings/{id}/generate-brd` in Meeting Master proxies meeting context into brd-agent's BRD pipeline.

## 6. Local URLs (after `start-demo.ps1`)

- Meeting Master API + UI: `http://127.0.0.1:5098` — Swagger at `/docs`
- RequireWise API + UI:    `http://127.0.0.1:8025` — `/health`, `/api/list-brds`

## 7. Current health (validated 2026-05-14)

13/13 e2e checks pass. See [TESTING.md](TESTING.md#last-run) for full output. EHI sample run: **69.4**, completeness **98.3**, leakage **40.0**, automation **100**, workspace processed meetings **45**.

## 8. Where to add a new feature — quick map

| If you want to… | Touch this |
|---|---|
| Add a new meeting-level metric | [meeting-master/backend/services/kpi.py](meeting-master/backend/services/kpi.py) → `compute_meeting_kpis` |
| Add a workspace-level metric | same file → `compute_portfolio_kpis`, then surface via `GET /api/v1/kpis/business-overview` |
| Add a Meeting Master endpoint | [meeting-master/backend/api.py](meeting-master/backend/api.py) — group is split by `tags=[...]` |
| Change BRD generation behavior | [brd-agent/backend/server.py](brd-agent/backend/server.py) → `/api/new-brd`, `/api/update-brd`, `/api/generate-brd-from-email` |
| Change dashboard cards | [brd-agent/frontend/dashboard.js](brd-agent/frontend/dashboard.js) + `POST /api/dashboard-data` in server.py |
| Add a new AI provider | [meeting-master/backend/services/ai.py](meeting-master/backend/services/ai.py) |
| Add an external webhook step | [meeting-master/backend/services/webhook.py](meeting-master/backend/services/webhook.py) |
| Persist new fields | `Meeting` model in [meeting-master/backend/models.py](meeting-master/backend/models.py) + storage merge logic |

## 9. Conventions worth knowing

- All times use IST (`Asia/Kolkata`) for human-facing strings — see top of [api.py](meeting-master/backend/api.py).
- `try: from . import …` / `except ImportError: import …` dual import pattern lets `api.py` run as package OR as script.
- The brd-agent's older `fastapi==0.104.1` / `pydantic==2.5.2` overwrites Meeting Master's pinned versions during setup — known but harmless (both apps still boot). Don't try to "fix" by re-pinning unless you're going to align both.
- `AUTH_DISABLED=true` in dev means *every* protected endpoint accepts anonymous calls. Don't ship that flag.

## 10. Things explicitly NOT in this repo

- No database. No Docker compose for local (docker files exist for prod-style). No CI/CD config in this workspace.
- No Python unit tests under `pytest`. The only automated test is the PowerShell e2e ([scripts/test-e2e.ps1](scripts/test-e2e.ps1)). See [TESTING.md](TESTING.md) for how to extend it.
