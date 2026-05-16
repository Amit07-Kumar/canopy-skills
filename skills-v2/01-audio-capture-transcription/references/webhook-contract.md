# transcribe-speakers webhook — request/response contract

## URL

`POST https://imworkflow.intermesh.net/webhook/transcribe-speakers`

## Request

```
Content-Type: multipart/form-data; boundary=...
X-Language:   hi | en | unknown        # optional, defaults to "unknown"
X-Model:      saaras:v3                # optional, default model
X-Timestamps: true | false             # optional
X-Session-Id: arbitrary-correlation-id # optional

[binary file under field name "audio"]
```

`audio` is the canonical field name. The Parse metadata Code node is defensive
and accepts any key — `audio0`, `data`, `file` all work — but our client always
sends `audio`.

## Response (HTTP 200, ~30–90s)

Success shape (the workflow Respond-to-Webhook node returns this JSON body):

```json
{
  "Speaker 1": "First speaker's complete utterance, multiline if needed...",
  "Speaker 2": "Second speaker's complete utterance...",
  "Speaker 3": "..."
}
```

The keys are always `Speaker <N>` strings. Diarization is performed by Sarvam.
Speakers are numbered by appearance order in the audio.

## Failure modes

| Symptom | Cause |
|---|---|
| 0.3s response, HTTP 200, empty body | Sarvam returned 429 / 5xx; workflow short-circuited. Probe Sarvam directly. |
| `{"error": "No audio binary found"}` | Parse metadata Code node only reads `$binary.audio`, no fallback to first key. |
| 502 / timeout >120s | Webhook timed out; check Sarvam status page or n8n executions tab. |
| Returns one speaker only | Audio is too short for Sarvam diarization (typically <10s of speech). |
