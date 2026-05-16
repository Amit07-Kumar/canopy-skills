# Features & Extension Points

What exists today and the cleanest place to plug in new behavior. Pair with [ARCHITECTURE.md](ARCHITECTURE.md) for the endpoint inventory.

---

## 1. Existing capabilities

### Meeting Master (`:5098`)

- **Capture** — upload audio (`/api/v1/meetings/upload`) or send raw text (`/api/v1/meetings/process-text`). Both run through the same downstream pipeline.
- **Transcription** — Deepgram, Groq Whisper, or Sarvam (Indian languages). Selection via `DEFAULT_STT_PROVIDER` or per-user `UserSettings`.
- **LLM extraction** — tasks, summary, calendar events, MoM email. Provider via OpenRouter / OpenAI / Anthropic / Gemini. Auto-merges system prompt into user message for models that don't support `system` role (gemma, gemini).
- **JSON-tolerant parsing** — `_extract_json()` strips markdown fences before parsing.
- **n8n webhook pipeline** (`USE_N8N_WEBHOOKS=true` by default) — transcribe, summarize, google-tools, send-email each routed to an n8n flow. Falls back to local pipeline if a webhook fails.
- **Auto-dispatch** — if recipients are present, MoM email is sent automatically; result reflected in `meeting.automation.auto_sent_email`.
- **Manual dispatch** — `/api/v1/meetings/{id}/send-email` lets the UI override the auto-send.
- **Calendar booking** — `/api/v1/calendar/authorize` + `/api/v1/calendar/events`.
- **Per-user BYOK** — `/api/v1/settings` stores provider, model, API key per user.
- **Team roster** — `/api/v1/team` CRUD.
- **KPIs** — per-meeting and workspace-wide (see §3).
- **BRD bridge** — `/api/v1/meetings/{id}/generate-brd` ships meeting context into brd-agent's BRD pipeline.
- **PWA frontend** — installable web app at `/` (manifest + service worker).
- **Guest auth + Descope** — anonymous device-bound JWTs for demo; Descope for prod logins.

### RequireWise / BRD Agent (`:8025`)

- **BRD generation** — `/api/new-brd` (from scratch), `/api/update-brd` (patch existing), `/api/generate-brd-from-email` (inbound-email → BRD).
- **BRD inventory** — `/api/list-brds` enumerates Google-Doc-backed BRDs with preview links.
- **Summarization** — `/api/transcript-summary` and `/api/audio-summary` for ad-hoc summarization not tied to a stored meeting.
- **Task assignment** — `/api/assign-tasks` distributes extracted tasks across owners.
- **Cross-app dashboard** — `/api/dashboard-data` aggregates KPIs from Meeting Master into the four-card UI ([brd-agent/frontend/dashboard.js](brd-agent/frontend/dashboard.js)).
- **Conflict detection** — `/api/conflict-detection` flags cross-meeting contradictions.
- **Knowledge graph** — `/api/knowledge-graph` returns an entity-relationship view.
- **OpenProject integration** — `/api/openproject-tickets` enumerates tickets.
- **Generic integration trigger** — `/api/trigger-integration` for ad-hoc webhook firing.
- **Project taxonomy** — `/api/config` returns the project list from [config.json](brd-agent/backend/config.json) (currently 7 hard-coded projects).

## 2. Demo-narrative features (what the README sells)

- Real business execution KPIs (EHI, completeness, leakage, automation) — not vanity metrics.
- Cross-app dashboard with live execution health.
- Meeting → BRD bridge with grounded meeting context.
- Windows PowerShell scripts for install/start/stop/validate.

## 3. KPIs (the headline metric story)

Source: [meeting-master/backend/services/kpi.py](meeting-master/backend/services/kpi.py).

| KPI | Function | Inputs | Surfaced at |
|---|---|---|---|
| **Execution Health Index (EHI)** | `compute_meeting_kpis` | tasks, automation, action-speed | `/api/v1/meetings/{id}/kpis`, `/api/v1/kpis/overview`, `/api/v1/kpis/business-overview` |
| **Context Completeness Score** | `compute_meeting_kpis` | transcript length, summary, MoM fields filled | same |
| **Action Leakage Rate** | `compute_meeting_kpis` | commitments detected (regex over transcript) vs. structured tasks | same |
| **Automation Coverage** | `compute_portfolio_kpis` / dashboard mapping | dispatch_success + auto_sent_email rates | `/api/v1/kpis/business-overview`, `/api/dashboard-data` |
| **Action Speed** | `_action_speed_score` | time_to_action_seconds, email_ready, calendar_ready | rolled into EHI |

The commitment detector uses a verb-trigger regex (`will|should|need to|must|follow up|schedule|send|prepare|deploy|fix|share|review|call|draft|create|update`). Adding a new commitment verb only requires editing `COMMITMENT_PATTERN`.

## 4. Where to extend — recipes

### Add a new KPI

1. Add the computation to `compute_meeting_kpis` (per-meeting) or `compute_portfolio_kpis` (workspace) in [services/kpi.py](meeting-master/backend/services/kpi.py).
2. If it should appear on the dashboard, map it in the `metrics` block of `/api/dashboard-data` ([brd-agent/backend/server.py](brd-agent/backend/server.py) → look for `dashboard-data` handler) and render in [brd-agent/frontend/dashboard.js](brd-agent/frontend/dashboard.js).
3. Add an assertion to [scripts/test-e2e.ps1](scripts/test-e2e.ps1) — confirm the field appears in the meeting-KPI response and is non-null after `process-text`.

### Add a new meeting endpoint

1. Append to [meeting-master/backend/api.py](meeting-master/backend/api.py) under the right `tags=[...]` group; declare request/response models in [models.py](meeting-master/backend/models.py).
2. If it mutates a meeting, route through `get_storage_service()` so the JSON store stays consistent.
3. Add an e2e check (see [TESTING.md §5](TESTING.md)).

### Add a new AI provider

1. Extend the `ModelProvider` enum + provider router in [services/ai.py](meeting-master/backend/services/ai.py).
2. Honor the system-prompt-merge fallback if the provider lacks `system` role support.
3. Run through `/api/v1/debug/llm` to smoke-test in isolation.

### Add a new webhook step

1. Add a function in [services/webhook.py](meeting-master/backend/services/webhook.py) following the existing `transcribe_audio_webhook` shape (httpx.AsyncClient, env-configured URL, timeout `N8N_WEBHOOK_TIMEOUT`).
2. Add the env URL constant in [config.py](meeting-master/backend/config.py).
3. Wire into the relevant API handler, with a local fallback.

### Add a new project to the BRD project list

Edit [brd-agent/backend/config.json](brd-agent/backend/config.json) — no code change needed, the frontend pulls from `/api/config`.

### Add a new RequireWise dashboard card

1. Extend the `/api/dashboard-data` response shape in [brd-agent/backend/server.py](brd-agent/backend/server.py).
2. Render in [brd-agent/frontend/dashboard.js](brd-agent/frontend/dashboard.js) (cards are layout-driven, not data-driven; add a new section).
3. Keep the data source coming from Meeting Master so the demo "single source of truth" story stays clean.

### Persist a new field on a meeting

1. Add it to the `Meeting` model in [models.py](meeting-master/backend/models.py).
2. Make sure the merge logic in `services/storage.py` (or the relevant handler) writes it.
3. If it should impact KPIs, hook it in [services/kpi.py](meeting-master/backend/services/kpi.py).
4. Bump `API_VERSION` in [config.py](meeting-master/backend/config.py) if external clients consume the shape.

## 5. Internal "skills" (playbook docs under `.github/skills/`)

These are reference docs the team uses to keep demo behavior consistent — worth reading before changing the corresponding area:

| Skill | Covers |
|---|---|
| [business-kpi-storytelling](.github/skills/business-kpi-storytelling/SKILL.md) | How to talk about the four headline KPIs |
| [execution-command-center](.github/skills/execution-command-center/SKILL.md) | Overall demo narrative |
| [hackathon-e2e-validation](.github/skills/hackathon-e2e-validation/SKILL.md) | What the e2e script must always cover |
| [meeting-master-kpis](.github/skills/meeting-master-kpis/SKILL.md) | KPI formulas and edge cases |
| [meeting-to-brd-bridge](.github/skills/meeting-to-brd-bridge/SKILL.md) | How meeting context flows into BRD generation |
| [portable-demo-setup](.github/skills/portable-demo-setup/SKILL.md) | The PowerShell-script-driven Windows setup |

## 6. Things to be careful about when extending

- **Don't break `/api/v1/kpis/business-overview`** — it's the only consumer surface for the brd-agent dashboard. Add fields, don't rename.
- **Don't reintroduce auth on the workspace overview** — by design it's unauthenticated so the dashboard can poll without a session.
- **Don't tie a feature to live provider keys** without a local fallback. The e2e runs without any AI keys configured.
- **Don't write to `data/store.json` directly** — go through `get_storage_service()` so the in-memory cache stays consistent.
- **Keep `AUTH_DISABLED=true` dev-only.** It bypasses every protected route. Any deploy-style script must unset it.
