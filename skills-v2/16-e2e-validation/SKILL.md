---
name: e2e-validation
description: Real-flow end-to-end test harness. Five scripts that exercise every layer of the product — Sarvam transcription, n8n AISummarization, translation, dispatch, BRD generation, dashboard live metrics, filesearch RAG — using real services, real audio, and real persisted outputs. Zero mocks.
---

# End-to-End Validation

## When to use this skill

- Before declaring any change "done" — run the full suite.
- Before a demo — confirm every layer is healthy.
- After an upstream provider hiccup (Sarvam credits, Gemini quota,
  LLM gateway) — re-verify the chain end-to-end.
- When investigating an intermittent failure — run repeatedly to
  confirm reproducibility.

## How to apply

### Five scripts in this repo's root

| Script | Coverage | Runtime |
|---|---|---|
| `scripts/test-e2e.ps1` | 13 PowerShell checks (health, guest auth, process-text, KPIs, BRD, email send, dashboard refresh) | ~3-4 min |
| `e2e_full_validation.py` | text-only path: process-text → BRD → dashboard, with mock-removal sanity asserts | ~3 min |
| `e2e_audio_validation.py` | real audio.mp3 upload → completed meeting → all asserts on shape | ~2 min |
| `e2e_final_validation.py` | filesearch status → ingest text → search → audio upload → translation → BRD → dashboard → manual /translate | ~5 min |
| `probe_transcribe.py` / `probe_google_tools.py` | direct n8n webhook smoke (skips meeting-master) | 30 sec each |

### Recommended order

```powershell
cd D:\10xHackathon

# 0) Cold restart both services so each test starts from a known state
.\scripts\start-demo.ps1

# 1) PowerShell suite — covers most basics
.\scripts\test-e2e.ps1

# 2) Text-path E2E with mock-removal asserts
python e2e_full_validation.py

# 3) Real audio E2E
python e2e_audio_validation.py

# 4) The comprehensive run (translation + filesearch + BRD + dashboard)
python e2e_final_validation.py
```

Expected: each one ends with a `PASS` summary block and exit code 0.

### Direct webhook probes (when the chain looks broken)

```powershell
python probe_transcribe.py        # n8n Sarvam transcription smoke
python probe_google_tools.py      # n8n google_tool_event smoke
python test_translate.py          # brd-agent /api/translate smoke (UTF-8 round trip)
```

These bypass meeting-master and hit the n8n / brd-agent directly so you
can isolate where a failure is happening.

## Asserts each script enforces

### `test-e2e.ps1` (13 checks)

1. Meeting Master `/health` → 200
2. BRD agent `/health` → 200
3. `POST /api/dashboard-data` → live metrics object
4. `GET /api/v1/kpis/business-overview` → portfolio KPIs
5. `POST /api/v1/auth/guest` → access_token (not just `token`)
6. `POST /api/v1/meetings/process-text` with realistic transcript → completed
7. `GET /api/v1/meetings/{id}` → meeting record
8. `GET /api/v1/meetings/{id}/kpis` → KPI dict
9. `GET /api/v1/kpis/overview` (user-scoped)
10. `GET /api/v1/kpis/business-overview` (workspace-scoped)
11. `POST /api/v1/meetings/{id}/generate-brd` → 200 with BRD slug
12. `POST /api/v1/meetings/{id}/send-email` (manual send) → 200
13. `POST /api/dashboard-data` again → numbers incremented vs step 3

### `e2e_full_validation.py`

- Sanity asserts on mock-removal: `/calendar/authorize` returns 501,
  `/api/openproject-tickets` returns `source: not-configured` (no hardcoded WP-*).
- Process a realistic transcript, verify all field shapes.
- Generate BRD, verify ≥ 1200 chars, all required headings present,
  ≤ 4 TBDs unless doc is ≥ 4000 chars.
- Persist BRD slug to `local_brds.json` and verify lookup.
- Dashboard `brd_count > 0`, `processed_meetings > 0`, all data sources
  status: `live`.

### `e2e_audio_validation.py`

- Upload real audio.mp3 (Hindi sales call).
- Poll until completed (8-min cap).
- Verify `raw_transcript` has non-ASCII chars (real Hindi).
- Verify `model_used` is `n8n-webhook-pipeline` (no silent fallback).
- Verify task count > 0, diarization preserved (multiple speakers).
- Verify `automation.dispatch_success = true`.

### `e2e_final_validation.py`

- Filesearch `/status` reachable.
- Ingest a launch-style email; document count increments.
- Search the ingested doc; quota-throttle tolerated honestly.
- Real audio upload with monotonic-progress assertion (no backwards jumps).
- `transcript_en` has dramatically fewer non-ASCII chars than `raw_transcript`
  → translation ran.
- Generate BRD ≥ 1500 chars with all required sections.
- Dashboard reflects new BRD (`brd_count` increments).
- Manual `/translate` endpoint re-runs translation successfully.

## How to add a new E2E assertion

1. Pick the right harness (text-only → `e2e_full_validation`, audio →
   `e2e_audio_validation`, comprehensive → `e2e_final_validation`).
2. Add a new `step(N, "description")` and an `ok(...)` / `fail(...)` call.
3. Keep asserts on **real outputs**, never on placeholder shapes.
4. Run repeatedly — flakiness is information, not noise. If the assert
   is flaky, the underlying behavior is flaky too.

## Scripts shipped with this skill

[`scripts/audit_no_mocks.py`](scripts/audit_no_mocks.py) — greps the repo for
the canonical mock-data patterns we've eradicated (WP-1..WP-5, placeholder=true,
SAMPLE_BRD_PROMPT, fake names like Rahul/Neha/Priya from earlier ad-hoc tests).
Run before any release.

## Related skills

- Every other skill — this skill is the verification layer that proves
  every other skill works end-to-end with real services.
