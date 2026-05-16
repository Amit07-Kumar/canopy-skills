# Sarvam Real-Time Meeting Transcription — Production Design

> What Sarvam actually offers (verified live against `api.sarvam.ai` on 2026-05-15):
>
> - **Real-time `POST /speech-to-text`** — under 30 s audio, NO diarization.
> - **Batch `POST /speech-to-text/job/init`** — supports speaker diarization, multi-step Azure-blob upload + async polling.
> - **No native WebSocket / streaming** in Sarvam's public API.
> - **Auth header**: `api-subscription-key: <key>` (NOT `Authorization: Bearer …`).

This file documents the two-workflow design we ship in `utils/`:

1. **`sarvam_realtime_transcription.workflow.json`** — chunked near-real-time path with simple diarization (rotation OR client-supplied speaker label).
2. **`sarvam_batch_diarization.workflow.json`** — full Sarvam batch flow with real diarization for the eventual "polished transcript" pass.

---

## 1. Architecture

```
┌───────────────────────────┐         ┌──────────────────────────┐
│  Browser microphone /     │   HTTP  │  n8n Realtime Workflow   │
│  WebRTC capture (client)  │ ──────► │  /webhook/sarvam-realtime│
│  Slices into 20–30 s WebM │         │  (chunk → Sarvam STT)    │
└───────────────────────────┘         └──────────┬───────────────┘
       ▲                                          │ per-chunk
       │  Server-Sent Events / WebSocket          │ JSON line
       │  back to UI for live captions            ▼
       │                              ┌──────────────────────────┐
       │                              │ Live caption UI / DB     │
       │                              └──────────────────────────┘

(Once the meeting ends, fire the full audio through the Batch workflow
 for the polished diarized transcript that backs the BRD generation.)

┌───────────────────────────┐         ┌──────────────────────────┐
│  End-of-meeting full      │   HTTP  │  n8n Batch Workflow      │
│  recording (multipart)    │ ──────► │  /webhook/sarvam-batch-  │
│                           │         │  diarize                 │
│                           │         │  init → blob upload →    │
│                           │         │  start → poll → diarized │
└───────────────────────────┘         └──────────────────────────┘
```

## 2. Why this shape

- Sarvam's real-time endpoint **caps at 30 s per request** — a hard server-side limit (the audio you uploaded earlier hit `Audio duration exceeds the maximum limit of 30 seconds`).
- Diarization on the real-time endpoint is **explicitly rejected** by Sarvam (`Diarization is not supported in the real-time API`).
- So a single workflow can't do "live + diarized" — you need two: live captions while the meeting is in progress (no diarization), and a polished pass after.
- Sarvam batch returns `diarized_transcript` with `speaker_id` per utterance — that's the real diarization.

## 3. Required n8n setup

### 3.1 Set the Sarvam API key as an n8n environment variable

In your n8n container's env: `SARVAM_API_KEY=sk_e8rpbyf6_…`.

Or, if using n8n cloud: Settings → Variables → add `SARVAM_API_KEY` with the value.

Both workflows reference it as `{{ $env.SARVAM_API_KEY }}` — no credential object needed.

### 3.2 Import the workflows

```bash
# Via n8n UI: ⋮ → Import from File → select utils/sarvam_*.workflow.json
# Or via REST API:
curl -X POST https://imworkflow.intermesh.net/rest/workflows \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  --data-binary @utils/sarvam_realtime_transcription.workflow.json
```

After import, **activate both workflows** so their webhooks go live.

### 3.3 Verify webhook paths

```
POST https://<your-n8n-host>/webhook/sarvam-realtime
POST https://<your-n8n-host>/webhook/sarvam-batch-diarize
```

---

## 4. API contracts (the part your client integrates against)

### 4.1 Real-time chunk endpoint

```
POST /webhook/sarvam-realtime
Content-Type: multipart/form-data
Headers (optional):
  X-Session-Id: <stable id across the whole meeting>
  X-Chunk-Index: <0-based int>
  X-Speaker: <"Priya"|"Speaker A">    # optional, overrides simple rotation
  X-Language: en-IN|hi-IN|unknown
  X-Model: saarika:v2.5

Form parts:
  audio: <30-second audio blob, any of WAV/MP3/WebM/OGG/M4A>
```

Response:
```json
{
  "session_id": "abc",
  "chunk_index": 0,
  "speaker": "Speaker 1",
  "language_code": "en-IN",
  "transcript": "Priya will finalize the Q3 OKRs by Friday.",
  "line": "Speaker 1: Priya will finalize the Q3 OKRs by Friday.",
  "received_at": "2026-05-15T15:32:11Z",
  "transcribed_at": "2026-05-15T15:32:14Z",
  "sarvam_request_id": "20260515_…",
  "error": null
}
```

### 4.2 Batch diarization endpoint

```
POST /webhook/sarvam-batch-diarize
Content-Type: multipart/form-data
Headers (optional):
  X-Session-Id, X-Language, X-Model, X-Timestamps: true|false

Form parts:
  audio: <full meeting recording — any length>
```

Response (after polling — the workflow handles it):
```json
{
  "job_id": "20260515_…",
  "status": "Completed",
  "transcript": "Speaker 1: Hello team.\nSpeaker 2: Good morning.\n…",
  "diarized_transcript": {
    "entries": [
      { "speaker_id": "SPEAKER_1", "start": 0.0, "end": 3.2,
        "transcript": "Hello team." },
      { "speaker_id": "SPEAKER_2", "start": 3.4, "end": 6.1,
        "transcript": "Good morning." }
    ]
  },
  "output_files": ["https://…blob.core.windows.net/…/output.json?sas=…"],
  "finished_at": "2026-05-15T15:36:22Z"
}
```

---

## 5. Example: browser microphone → near-real-time captions

Drop this into a `<script>` tag on the meeting-master frontend (or import as a JS module).

```javascript
// utils/browser_mic_streamer.js
const N8N_BASE = 'https://imworkflow.intermesh.net';
const SESSION_ID = `meet-${Date.now()}`;

let mediaRecorder, chunkIndex = 0;

async function startCapture() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: {
    channelCount: 1, sampleRate: 16000, echoCancellation: true
  }});
  // 25s segments so each request lands well under Sarvam's 30s cap.
  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
  mediaRecorder.ondataavailable = (e) => sendChunk(e.data);
  mediaRecorder.start(25000); // emit a chunk every 25s
}

async function sendChunk(blob) {
  if (!blob || blob.size === 0) return;
  const fd = new FormData();
  fd.append('audio', blob, `chunk_${chunkIndex}.webm`);
  const res = await fetch(`${N8N_BASE}/webhook/sarvam-realtime`, {
    method: 'POST',
    headers: {
      'X-Session-Id':  SESSION_ID,
      'X-Chunk-Index': String(chunkIndex),
      'X-Language':    'unknown'
      // 'X-Speaker':   'Priya'   // set this from your VAD if you can
    },
    body: fd
  });
  chunkIndex++;
  const data = await res.json();
  if (data.line) {
    document.getElementById('caption-stream').textContent += data.line + '\n';
  }
}

function stopCapture() {
  if (mediaRecorder) mediaRecorder.stop();
}
```

**Caveats:** MediaRecorder gives you Opus-in-WebM which Sarvam supports. If your meeting frontend is Google Meet / Zoom, capture system audio via the Screen Capture API with `audio: true` (Chrome only) or hook a Meet/Zoom bot.

---

## 6. Browser-side speaker hint (cheap diarization)

If you want better-than-rotation speaker labels without paying for Sarvam batch, use a tiny browser VAD to detect speaker changes and pass the label via `X-Speaker`:

```javascript
import * as vad from '@ricky0123/vad-web';
const m = await vad.MicVAD.new({
  onSpeechStart: () => { /* speaker block opens */ },
  onSpeechEnd:   () => { /* speaker block closes */ },
});
m.start();
```

Or use voice fingerprinting (`speaker-id-js` or similar) and tag each utterance with the matched speaker id. Pass that as `X-Speaker` in `sendChunk`.

---

## 7. curl examples

### Real-time chunk:
```bash
curl -X POST https://imworkflow.intermesh.net/webhook/sarvam-realtime \
  -H "X-Session-Id: demo-1" -H "X-Chunk-Index: 0" -H "X-Language: en-IN" \
  -F "audio=@chunk_0.webm;type=audio/webm"
```

### Batch with diarization (synchronous wait inside the workflow):
```bash
curl -X POST https://imworkflow.intermesh.net/webhook/sarvam-batch-diarize \
  -H "X-Session-Id: full-meeting-2026-05-15" -H "X-Language: en-IN" \
  -F "audio=@full_meeting.mp3;type=audio/mpeg"
```

### Direct Sarvam REST (no n8n):
```bash
# Real-time (≤30 s)
curl -X POST https://api.sarvam.ai/speech-to-text \
  -H "api-subscription-key: $SARVAM_API_KEY" \
  -F "file=@chunk.mp3;type=audio/mpeg" \
  -F "model=saarika:v2.5" -F "language_code=unknown"

# Batch init
curl -X POST https://api.sarvam.ai/speech-to-text/job/init \
  -H "api-subscription-key: $SARVAM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"saarika:v2.5","language_code":"unknown","with_diarization":true,"with_timestamps":true}'
```

---

## 8. Storage / persistence

Add a "Postgres: insert transcript line" node after `Label speaker + format line` if you want a durable transcript:

```sql
CREATE TABLE meeting_transcript (
  id            bigserial PRIMARY KEY,
  session_id    text        NOT NULL,
  chunk_index   integer     NOT NULL,
  speaker       text        NOT NULL,
  language_code text,
  transcript    text        NOT NULL,
  transcribed_at timestamptz DEFAULT now()
);
CREATE INDEX ON meeting_transcript(session_id, chunk_index);
```

Or pipe to Meeting Master's existing `/api/v1/meetings/process-text` endpoint at end-of-meeting — feed the full diarized transcript so Stage 2 (AISummarization) extracts MoM + tasks + calendar.

---

## 9. Live-caption UI (Server-Sent Events from n8n)

n8n's `respondToWebhook` is synchronous, so for live captions you have two patterns:

- **Long-polling** (simplest): client posts each chunk, waits for response, appends to caption stream. Latency = chunk size + Sarvam round-trip (~2-4s).
- **WebSocket frontend**: run a small WS gateway alongside n8n; client uploads chunks via HTTP, gateway pushes captions out via WS. Use the `sarvam-realtime` n8n webhook from your gateway code.

For most demos, long-polling is fine and avoids extra infra.

---

## 10. Error handling + retries

The real-time workflow uses `neverError: true` on the HTTP node so a 4xx from Sarvam flows through as JSON. The "Label speaker" node passes the error along untouched. Client should:

- Retry on `error.code === "rate_limit_error"` with exponential backoff
- Drop and resync on `error.code === "invalid_request_error"` (audio too long → resend smaller chunk)
- On 5xx: retry up to 2x, then fall back to local Whisper / Groq for that one chunk

The batch workflow's poll loop has a 10 s re-poll; jobs can take 30 s – 3 min depending on audio length. If you need a hard upper bound, add a counter in the `Wait 10s and re-poll` → If(`tries > 30`) → fail-out branch.

---

## 11. Scalability + production notes

- n8n workflow execution is async per webhook; you can fire 50 concurrent real-time requests against the same workflow.
- Sarvam's rate limit varies by tier — measure with `429` responses, back off the `retry-after` header. Add a Redis-based token-bucket node ahead of the HTTP request if you need strict shaping.
- For >100 concurrent sessions, host a Sarvam-direct service (Python FastAPI behind nginx) and skip n8n on the hot path — n8n is great for orchestration but not for high-QPS streaming.
- Batch jobs use Azure blob upload; the SAS tokens in the init response expire after ~5 days — don't cache them.

---

## 12. Optional integrations

| Source | How |
|---|---|
| Google Meet | Use Meet's API webhook or a Meet bot (e.g. `recall.ai`) → stream audio to `/webhook/sarvam-realtime` |
| Zoom | Zoom's RTMS endpoint → forward audio chunks via your gateway |
| WebRTC | Capture local stream via `getUserMedia`, slice via MediaRecorder (see §5) |
| Browser mic | Same as WebRTC; works without extra infra |
| Live captions | DOM update on each chunk response (see §5 sample) |
| DB storage | Postgres node after Label speaker (see §8) |
| Slack live captions | After Label speaker, add Slack node to post each line into a thread |

---

## 13. Files in this folder

```
utils/
├── SARVAM_REALTIME_TRANSCRIPTION.md          ← this file
├── sarvam_realtime_transcription.workflow.json  ← chunked near-real-time n8n workflow
├── sarvam_batch_diarization.workflow.json    ← async batch with diarization
├── browser_mic_streamer.js                   ← client-side mic capture + chunk POST
└── sarvam_test.sh                            ← smoke-test scripts for both webhooks
```
