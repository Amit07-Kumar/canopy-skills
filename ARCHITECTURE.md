# Architecture

High-level service map, endpoint inventory, and data flow. See [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for narrative, [FEATURES.md](FEATURES.md) for what each piece does.

---

## 1. Service map

```
                ┌────────────────────────┐         ┌────────────────────────┐
                │  RequireWise frontend  │         │ Meeting Master frontend │
                │  brd-agent/frontend    │         │ meeting-master/frontend │
                │  (HTML + dashboard.js) │         │ (HTML + app.js + sw.js) │
                └───────────┬────────────┘         └───────────┬─────────────┘
                            │  fetch                            │  fetch
                            ▼                                   ▼
              ┌─────────────────────────┐         ┌──────────────────────────┐
              │ brd-agent backend       │  HTTP   │ Meeting Master backend   │
              │ FastAPI :8025           │ ──────► │ FastAPI :5098            │
              │ brd-agent/backend/      │         │ meeting-master/backend/  │
              │   server.py             │         │   api.py + services/     │
              └─────────────┬───────────┘         └─────────────┬────────────┘
                            │                                    │
                            │ optional                           │ optional n8n
                            ▼                                    ▼
                  ┌──────────────────┐                ┌────────────────────────┐
                  │ n8n webhooks     │                │ STT (Deepgram/Groq/    │
                  │ (transcribe,     │                │  Sarvam) + LLM         │
                  │  summarize,      │                │ (OpenRouter/OpenAI/    │
                  │  google-tools,   │                │  Anthropic/Gemini)     │
                  │  send-email)     │                │ + Google Calendar      │
                  └──────────────────┘                └────────────────────────┘
```

Cross-app dependency: brd-agent calls Meeting Master via `MEETING_MASTER_API_BASE` (env, defaulted to `http://127.0.0.1:5098/api/v1`).

---

## 2. Meeting Master — `:5098`

Source: [meeting-master/backend/api.py](meeting-master/backend/api.py) (≈2500 lines). Routes grouped by FastAPI `tags`.

### Health & meta
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{status, started (IST), host, version}` |
| GET | `/` | Serves frontend SPA |
| GET | `/docs`, `/redoc` | OpenAPI |
| GET | `/sw.js`, `/manifest.json` | PWA assets |

### Auth (`tags=["Auth"]`)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/auth/config` | Public auth flags |
| GET | `/api/v1/auth/me` | Current user |
| POST | `/api/v1/auth/refresh` | Refresh JWT |
| POST | `/api/v1/auth/descope-login` | Descope flow |
| POST | `/api/v1/auth/guest` | Guest token (device_id, device_name) |

### Settings & team
| Method | Path | Notes |
|---|---|---|
| GET / PUT | `/api/v1/settings` | Per-user `UserSettings` (BYOK + STT prefs) |
| GET / POST | `/api/v1/team` | Team members |
| DELETE | `/api/v1/team/{email}` | Remove member |

### Meetings (the core)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/meetings/upload` | Multipart audio upload → triggers async processing |
| POST | `/api/v1/meetings/process-text` | **e2e tested.** Body: `{title, transcript, attendee_emails, participants}` → returns full meeting incl. `automation`, `mail`, KPIs |
| GET | `/api/v1/meetings` | Paginated list |
| GET | `/api/v1/meetings/{id}` | Full meeting record |
| PUT | `/api/v1/meetings/{id}` | Update |
| DELETE | `/api/v1/meetings/{id}` | Delete |
| GET | `/api/v1/meetings/{id}/kpis` | Per-meeting KPIs (EHI, completeness, leakage) |
| POST | `/api/v1/meetings/{id}/process` | Re-process |
| GET | `/api/v1/meetings/{id}/status` | Processing status + progress |
| POST | `/api/v1/meetings/{id}/generate-brd` | Bridge to brd-agent |
| POST | `/api/v1/meetings/{id}/send-email` | Manual MoM send |
| POST | `/api/v1/meetings/{id}/google-tools` | Trigger Google Tools n8n webhook |

### Insights (KPIs)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/kpis/overview` | **User-scoped** rollup |
| GET | `/api/v1/kpis/business-overview` | **Workspace-wide** rollup. Consumed by brd-agent dashboard |

### Calendar
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/calendar/authorize` | OAuth URL |
| POST | `/api/v1/calendar/events` | Create events |

### Debug (active only when `DEBUG_MODE=true`)
`/api/v1/debug/config`, `/api/v1/debug/test`, `/api/v1/debug/llm`, `/api/v1/debug/translate`, `/api/v1/debug/extract-tasks`, `POST /api/v1/debug/transcribe`.

### Services layer
- [services/storage.py](meeting-master/backend/services/storage.py) — JSON file persistence. Singleton via `get_storage_service()`.
- [services/ai.py](meeting-master/backend/services/ai.py) — LLM dispatch (OpenRouter / OpenAI / Anthropic / Gemini), system-prompt-merge fallback, JSON extraction.
- [services/kpi.py](meeting-master/backend/services/kpi.py) — `compute_meeting_kpis`, `compute_portfolio_kpis`, commitment regex, action-speed scoring.
- [services/webhook.py](meeting-master/backend/services/webhook.py) — `transcribe_audio_webhook`, `summarize_transcript_webhook`, `trigger_google_tools_webhook`, `trigger_email_send_webhook`, plus `map_webhook_to_meeting_updates`.

### Persisted shape (per meeting, roughly)

```jsonc
{
  "meeting_id": "uuid",
  "title": "...",
  "date": "ISO-8601",
  "status": "completed",
  "raw_transcript": "...",
  "transcript_en": "...",
  "summary": "...",
  "tasks": [ { "title": "...", "assignee": "...", "deadline": "..." } ],
  "calendar_events": [...],
  "mail": { "subject": "...", "body": "...", "to": "...", "cc": [] },
  "automation": {
    "dispatch_success": true,
    "auto_sent_email": true,
    "recipients": ["a@x.com", "b@x.com"]
  },
  "kpis": { "execution_health_index": 69.4, "context_completeness_score": 98.3, "action_leakage_rate": 40.0, "automation_coverage": 100 }
}
```

Storage path resolved at boot: `STORAGE_FILE` env → defaults to `data/store.json`. Uploads → `UPLOAD_DIR`.

---

## 3. RequireWise / BRD Agent — `:8025`

Source: [brd-agent/backend/server.py](brd-agent/backend/server.py).

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{status, service: "brd-agent"}` |
| GET | `/api/config` | Returns project list from [config.json](brd-agent/backend/config.json) |
| POST | `/api/update-brd` | Patch existing BRD |
| POST | `/api/new-brd` | Create BRD from scratch |
| GET | `/api/list-brds` | List Google-Doc-backed BRDs |
| POST | `/api/transcript-summary` | Summarize a transcript |
| POST | `/api/audio-summary` | Summarize an audio file |
| POST | `/api/assign-tasks` | Distribute tasks across owners |
| POST | `/api/google-tools` | Trigger Google integrations |
| POST | `/api/dashboard-data` | **e2e tested.** Body: `{project}` → returns `{data.metrics, data.recent_activity, ...}` for RequireWise UI |
| POST | `/api/conflict-detection` | Cross-meeting conflict signals |
| POST | `/api/knowledge-graph` | Entity / relationship graph |
| POST | `/api/trigger-integration` | Generic webhook trigger |
| POST | `/api/generate-brd-from-email` | Email → BRD |
| GET | `/api/openproject-tickets` | OpenProject integration |

### Dashboard data flow

`POST /api/dashboard-data` reaches into Meeting Master:

```
RequireWise UI
  └─ POST /api/dashboard-data {project}
       └─ GET MEETING_MASTER_API_BASE + "/kpis/business-overview"
            ← {total, execution_health, context_completeness, automation_coverage, recent_activity[]}
       ← {data: {metrics, recent_activity, ...}}
```

The `metrics` block back to the UI maps to four cards: Execution Health, Context Completeness, Action Leakage, Automation Coverage.

---

## 4. Config & environment knobs

Both scripts/start-demo.ps1 sets a few env vars before spawning:

| Env | Effect |
|---|---|
| `AUTH_DISABLED=true` | Skip JWT auth (dev only) |
| `DEBUG_MODE=true` | Enables `/api/v1/debug/*` and DEBUG logs |
| `JWT_SECRET` | Guest JWT signing key |
| `UPLOAD_DIR`, `STORAGE_FILE` | File-storage paths |
| `MEETING_MASTER_API_BASE` | brd-agent → meeting-master URL |
| `USE_N8N_WEBHOOKS=true` (default in config) | Route transcribe/summarize/etc. through n8n |
| `N8N_WEBHOOK_*` URLs | Override per-step webhook endpoints |
| `OPENROUTER_API_KEY`, `DEEPGRAM_API_KEY`, `GROQ_API_KEY`, `SARVAM_API_KEY` | AI / STT provider keys |
| `DEFAULT_LLM_MODEL`, `DEFAULT_STT_PROVIDER` | Defaults if no per-user BYOK |
| `DESCOPE_PROJECT_ID`, `AUTH_SERVICE_URL` | Production auth |

CORS allow-list (Meeting Master) hard-codes `meeting.lehana.in`, `meeting.aidhunik.com`, and `localhost:3000/5000`. To call from a non-listed origin you must either add it or run via the served frontend on `:5098`.

---

## 5. End-to-end happy path (text mode, what the e2e covers)

1. `POST /api/v1/auth/guest` → token
2. `POST /api/v1/meetings/process-text` with `{title, transcript, attendee_emails, participants}` — Meeting Master:
   - calls summarize webhook (or local fallback) on the transcript
   - extracts tasks / events / MoM mail
   - computes KPIs (`services/kpi.py`)
   - auto-dispatches MoM email if recipients exist (`automation.auto_sent_email`)
   - persists to `data/store.json`
3. `GET /api/v1/meetings/{id}` — recover full record
4. `GET /api/v1/meetings/{id}/kpis` — per-meeting EHI / completeness / leakage
5. `GET /api/v1/kpis/business-overview` — workspace rollup, no auth (intentional, dashboard consumer)
6. `POST /api/v1/meetings/{id}/generate-brd` — bridge into brd-agent
7. `POST /api/v1/meetings/{id}/send-email` — manual MoM dispatch
8. `POST /api/dashboard-data` (brd-agent) — RequireWise dashboard reads the new state
