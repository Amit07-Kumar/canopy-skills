---
name: audio-capture-transcription
description: Capture meeting audio (mic, upload, or paste-as-text) and pipe it through the n8n Sarvam batch transcription workflow to produce a speaker-diarized transcript.
---

# Audio Capture & Transcription

## When to use this skill

- The user wants to record a live meeting, upload an existing audio file
  (mp3/wav/m4a/webm), or paste a transcript and have the system extract
  speaker-tagged text.
- You're debugging "transcript came out empty" or "wrong language detected".
- You need to wire a new audio source into the existing pipeline.

## How to apply

### Front-end capture (mic / upload / paste)

- `meeting-master/frontend/index.html` — Record / Upload / Paste tabs.
  Record tab is FIRST so the mic is the first interactive thing on the page.
- `meeting-master/frontend/app.js`:
  - `toggleRecording()` — MediaRecorder with `audio/webm;codecs=opus`,
    visualizer, timer.
  - `handleFileSelect(file)` — accepts MIME prefix `audio/*` or `video/*`
    OR known extensions (mp3, m4a, webm, mp4, ogg, flac, opus, aac).
  - `processAudioBlob(blob)` — POSTs `multipart/form-data` with field
    `audio` to `/api/v1/meetings/upload`.

### Backend ingest

- `meeting-master/backend/api.py` → `POST /api/v1/meetings/upload`:
  - Saves audio under `UPLOAD_DIR/{meeting_id}.{ext}`.
  - Creates a meeting record with `status=PENDING`.
  - Background task `process_meeting_task` picks it up.

### n8n Sarvam batch workflow

- Workflow ID `O8KEIwhr8JE3XRDQ` on `imworkflow.intermesh.net`.
- Webhook path `/webhook/transcribe-speakers`.
- The "Parse metadata" Code node must read the binary from **any** key
  (`audio`, `audio0`, `data`, etc.) using `Object.entries($binary)[0]`,
  and re-emit it as `binary.audio` so downstream Sarvam nodes find it.
- Sarvam credentials are stored as an n8n **Header Auth** credential
  named `Sarvam API` with `Name=api-subscription-key, Value=<key>`.
  All six Sarvam HTTP Request nodes reference this credential — no
  hardcoded keys, no `$env.SARVAM_API_KEY` (the latter is blocked by
  the n8n server).

### Local backend caller

- `meeting-master/backend/services/webhook.py:_transcribe_audio_via_n8n`:
  - Posts `files={"audio": (filename, file_bytes, content_type)}`.
  - 120s timeout (`N8N_WEBHOOK_TIMEOUT`).
  - On non-200 or empty payload, returns `{}` → caller marks meeting FAILED
    with message `"Transcription webhook returned empty result"`.

### Status states for the user

| Stage | Progress | Where |
|---|---|---|
| `queued` | 0–18 | upload accepted, background task queued |
| `transcribing` | 28 | Sarvam batch job submitted, polling for completion |
| `reading_transcript` | 28 | text-only path (no audio) |
| `summarizing` | 60 | speaker_map → AISummarization |
| `drafting_outputs` | 84 | mapping AISummarization → meeting fields |
| `translating` | 92 | non-English transcript → English (see [[02-transcript-translation]]) |
| `dispatching` | 96 | google_tool_event call (see [[13-auto-dispatch-flow]]) |
| `completed` | 100 | meeting locked in |

The progress bar is monotonic — see [[11-frontend-ux-patterns]] for the
contract.

## Common failures & root causes

- **"No audio binary found"** — the n8n Parse metadata node only reads
  `$binary.audio` instead of falling back to the first binary entry. Fix in
  [[12-n8n-integration]] → workflow 1.
- **HTTP 200 with empty body in <1s** — Sarvam returned `429 No credits
  available` OR an early Respond node fires. Probe Sarvam directly with
  the key first.
- **"Transcription webhook returned empty result"** — the n8n workflow
  returned an empty body. Open Executions in n8n to find the red node.
- **Wrong language detected** — Sarvam's `language_code=unknown` is the
  default; pass `X-Language: hi` / `en` etc. header for stricter routing.

## Related skills

- [[02-transcript-translation]] — what happens to the speaker_map next
- [[03-ai-summarization]] — how the speaker_map becomes MoM/Task/Calendar
- [[11-frontend-ux-patterns]] — recording UX, monotonic progress, status poll cap
- [[12-n8n-integration]] — Parse metadata node, Sarvam credentials, troubleshooting

## Reference materials

- [`references/webhook-contract.md`](references/webhook-contract.md) — exact request/response shapes
- [`references/parse-metadata-node.js`](references/parse-metadata-node.js) — canonical Code node body
