---
name: n8n-integration
description: How the product talks to two separate n8n servers (imworkflow.intermesh.net for Sarvam transcription + AISummarization, n8n.backend.lehana.in for google_tool_event). Covers credential management, workflow topology, manual fix runbook, and troubleshooting via the Executions tab.
---

# n8n Integration

## When to use this skill

- You need to wire a new workflow into the product (add a webhook,
  authenticate to a new API).
- A workflow is misbehaving — find the failing node via Executions and
  apply the right fix.
- You're rotating Sarvam / LLM gateway keys — do it in the credential
  store, not by hardcoding into every node.

## How to apply

### Two n8n instances

| Instance | Purpose | Workflows |
|---|---|---|
| `imworkflow.intermesh.net` | Speech + AI | transcribe-speakers, AISummarization |
| `n8n.backend.lehana.in` | Productivity tools | google_tool_event, update-brd, new-brd, AISummarization (duplicate) |

This split is by design — speech-heavy workloads stay on one instance,
Google Workspace integrations on the other.

### Three workflows we depend on

#### 1. `transcribe-speakers` (imworkflow)

Webhook: `/webhook/transcribe-speakers` (workflow ID `O8KEIwhr8JE3XRDQ`).

Topology:
```
Webhook (receive audio, binary)
  → Parse metadata (Code: normalize $binary key, build session_id)
  → Sarvam: create batch job (HTTP, needs api-subscription-key)
  → Sarvam: request upload URL (HTTP, needs api-subscription-key)
  → Resolve upload target (Code)
  → Upload audio to signed URL (HTTP, Azure SAS — no Sarvam header)
  → Sarvam: start job (HTTP, needs api-subscription-key)
  → Initial wait 15s
  → Sarvam: poll job status (HTTP, needs api-subscription-key)
  → Normalize job status (Code)
  → Job completed?     ── false → Job failed? ── true → Respond failure JSON
        ↓ true                                  ── false → Wait 10s and re-poll
  → Need download files?    ── false → Respond inline JSON
        ↓ true
  → Sarvam: request download URLs (HTTP, needs api-subscription-key)
  → Resolve download target (Code)
  → Download transcript payload (HTTP, needs api-subscription-key)
  → Respond downloaded JSON
```

Key contracts:
- Webhook node `binaryData: true`, `binaryPropertyName: audio`,
  `responseMode: responseNode`.
- Parse metadata uses `Object.entries($binary)[0]` (see
  [[01-audio-capture-transcription]]).
- Sarvam HTTP nodes use an n8n **Header Auth credential**
  named `Sarvam API` with `api-subscription-key: <key>`. NO env vars
  (`N8N_BLOCK_ENV_ACCESS_IN_NODE` is on at the server level).

#### 2. `AISummarization` (imworkflow)

Webhook: `/webhook/AISummarization`. Single Groq AI Scrum Assistant
node + Respond to Webhook.

Key contracts:
- Input: JSON keyed by `Speaker N`.
- Output: `[{MOM, Task, calender}]` — single-item array.
- Groq output parser enforces strict JSON schema with task category enum.
  Tolerate `Other` / `Meeting` after schema relax to avoid validation
  failures. See [[03-ai-summarization]].

#### 3. `google_tool_event` (n8n.backend.lehana.in)

Webhook: `/webhook/google_tool_event`. Two parallel branches from the
Webhook node:

```
Webhook (POST)
  ├→ Send email (Gmail node, reads body.MOM[0], body.recipients)
  └→ Code in JavaScript: Fan out calendar events
       → Create an event (Google Calendar node, fires N times)
```

Key contracts:
- Send email is **independent** of the calendar branch. Even if calendar
  fan-out is empty, the email still goes out.
- Calendar fan-out: see [[05-calendar-dispatch]] for the canonical Code
  node body.
- Create-an-event `Attendees` field must receive a comma-string, not
  array — n8n internally calls `.split(',')`. See
  [[05-calendar-dispatch]] for the bug history.

### Credential management

For Sarvam, the recommended path is the n8n **Header Auth** credential:

1. In n8n: avatar → Settings → Credentials → **+ Create credential** → search
   "Header Auth".
2. Name it `Sarvam API`.
3. Set `Name = api-subscription-key`, `Value = <Sarvam key>`.
4. In each Sarvam HTTP Request node: Authentication → **Generic Credential
   Type** → **Header Auth** → pick `Sarvam API`.
5. Delete the hardcoded `api-subscription-key` row from each node's
   Headers section.
6. Toggle workflow Active OFF → ON.

This way the key lives in ONE place, encrypted; rotating only edits the
credential, not 6 nodes.

If env vars are blocked (`access to env vars denied` error), hardcoding
keys directly in each node is acceptable as a fallback — less elegant
but functional. The product code does not depend on which approach n8n
uses.

### Manual fix runbook

See [`assets/manual-fixes.md`](assets/manual-fixes.md) for click-by-click
fixes for the four most common workflow regressions:

1. AISummarization rejecting `Other` category
2. google_tool_event returning 400 from Google Calendar API
3. transcribe-speakers returning empty body in <1s
4. `attendee.split is not a function` on Create-an-event

### Diagnosing failures

When a workflow fails:

1. Open the workflow editor.
2. Click **Executions** in the left sidebar.
3. Find the most recent execution (top of the list).
4. Click into it — the workflow shows colored nodes:
   - 🟢 green = succeeded
   - 🔴 red = failed (click for error message + input data)
   - ⚪ grey = never reached
5. The red node's panel shows the **exact** error string. That's the
   fastest path to a fix.

NEVER click "Execute workflow" or "Execute step" inside a webhook-
triggered workflow to test — there's no incoming binary, so `$binary` is
empty and `$json.body` is undefined. Always trigger via a real HTTP
request (our scripts/probes do this).

## Related skills

- [[01-audio-capture-transcription]] — transcribe-speakers
- [[03-ai-summarization]] — AISummarization
- [[05-calendar-dispatch]] — google_tool_event calendar branch
- [[06-email-dispatch]] — google_tool_event email branch

## Reference materials

- [`assets/manual-fixes.md`](assets/manual-fixes.md) — runbook for the four common workflow regressions
- [`references/credentials.md`](references/credentials.md) — Sarvam credential setup walkthrough
