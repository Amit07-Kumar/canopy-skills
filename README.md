# AI Execution Command Center

This workspace contains two connected apps:

- `meeting-master`: captures meetings, extracts actions, computes business KPIs, auto-dispatches follow-ups.
- `brd-agent`: turns the same context into BRDs and now shows a live execution dashboard powered by Meeting Master data.

## What makes this demo stronger now

- Real business execution KPIs instead of pitch-only metrics
- Cross-app dashboard in RequireWise with live execution health, context completeness, automation coverage, and recent follow-up activity
- Meeting-to-BRD bridge with grounded meeting context
- PowerShell scripts to install, start, stop, and validate the full demo on a Windows laptop

## KPI story for judges

- `Execution Health`: how ready the meeting is for actual execution
- `Context Completeness`: whether the meeting output is clear enough to act on without rework
- `Action Leakage`: commitments spoken in the meeting but not converted into structured follow-up
- `Automation Coverage`: how often the system closes the loop automatically through email/calendar dispatch

## Quick Start on Windows

1. Install dependencies:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-demo.ps1
```

2. Start both apps:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1
```

3. Run the end-to-end validation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-e2e.ps1
```

4. Stop both apps when done:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-demo.ps1
```

## Local URLs

- Meeting Master: `http://127.0.0.1:5098`
- RequireWise: `http://127.0.0.1:8025`

## Verified Sarvam Batch Flow

The long-audio transcription path is now verified against Sarvam's current batch API contract.

- Create job: `POST /speech-to-text/job/v1`
- Request signed upload URLs: `POST /speech-to-text/job/v1/upload-files`
- Start job: `POST /speech-to-text/job/v1/{job_id}/start`
- Poll status: `GET /speech-to-text/job/v1/{job_id}/status`
- Request signed download URLs: `POST /speech-to-text/job/v1/download-files`

Important implementation detail:

- Signed upload and download URLs must be used verbatim. Re-encoding or reconstructing the SAS URL can break Azure blob access.
- Meeting Master and RequireWise now use Sarvam batch for stage 1 long-audio transcription and do not silently replace a failed stage 2 summarization with synthetic local success on the real meeting/audio path.

## Optional File Search Context For BRDs

RequireWise can enrich BRD generation with external file-search context, intended for launch mails and other reference documents.

- Configure `FILE_SEARCH_API_BASE` to your file-search service base, for example `https://your-service/api`.
- The current integration expects a live `POST /search` route that accepts a JSON body with at least `{"query": "..."}`.
- Optional request-level overrides can be passed through `FILE_SEARCH_REQUEST_JSON` when your service needs fixed extra fields.
- Configure the same values in root `.env` so Docker passes them to `brd-agent` through `docker-compose.yml`.
- Meeting-to-BRD now forwards a focused `search_query`, and BRD Agent will append retrieved context before LLM generation when the service is configured.

Useful verification routes discovered on the reference Gemini file-search deployment:

- `GET /api/store-info`
- `GET /api/documents`
- `POST /api/search`

## Notes

- Meeting processing now relies on the real Sarvam batch plus AISummarization path for the core audio workflow and fails loudly when those real dependencies do not return structured output.
- KPI computation, auto-dispatch state, business overview, and BRD bridging remain locally testable.
- The new RequireWise advanced dashboard reads from `GET /api/v1/kpis/business-overview` in Meeting Master, so it surfaces workspace-wide business execution signals rather than guest-scoped empty data.