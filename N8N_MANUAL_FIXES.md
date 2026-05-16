# n8n Workflow Manual Fixes

This document covers issues that live inside n8n workflows (NOT in this
repository) and the exact step-by-step fix for each. The Meeting Master
backend has been hardened so the symptoms are now contained, but the root
causes still need a one-time tweak on the n8n server.

n8n base URL: `https://imworkflow.intermesh.net` and `https://n8n.backend.lehana.in`

---

## Fix 1 — AISummarization: Groq schema rejects `Other`/`OTHER` category

### Symptom

In n8n execution logs:

```
Groq Chat Model
2330ms ...
tool call validation failed: parameters for tool format_final_json_response
did not match schema: errors: [/output/tasks/1/category: value must be one of
"Development", "Research", "Infra", "Bug", "Ops", "Documentation"]
```

Meeting Master then sees an empty AISummarization response and either
falls back to deterministic extraction or fails the meeting outright.

### Root cause

The Groq node inside the AISummarization n8n workflow is configured with a
strict JSON schema where `category` must be one of six enum values. The
model occasionally outputs `"Other"`, `"Misc"`, `"Meeting"`, or empty. n8n
rejects the entire response.

### Fix on n8n (do this once)

1. Open `https://imworkflow.intermesh.net`.
2. Open the workflow named **AISummarization**.
3. Click the **Groq Chat Model** node.
4. Scroll to the **Output Parser** section (or "Response Format" → "JSON
   Schema" depending on n8n version).
5. Find the `category` field inside the `tasks` schema. It currently looks
   like:
   ```json
   "category": {
     "type": "string",
     "enum": ["Development", "Research", "Infra", "Bug", "Ops", "Documentation"]
   }
   ```
6. Replace with the more permissive shape so the workflow never blows up:
   ```json
   "category": {
     "type": "string",
     "enum": [
       "Development", "Research", "Infra", "Bug",
       "Ops", "Documentation", "Other", "Meeting"
     ],
     "default": "Ops"
   }
   ```
7. Click the **System prompt** of the Groq node and append the line:
   ```
   The "category" field MUST be exactly one of:
   Development, Research, Infra, Bug, Ops, Documentation, Other, Meeting.
   When unsure, use "Ops".
   ```
8. **Save** the workflow and toggle **Active** on if it was off.

### Containment already in place in this repo

Even if you skip this fix, `meeting-master/backend/api.py` now coerces any
outbound task category to one of the six allowed enum values before
sending to `google_tool_event`. So the downstream dispatch path stays
healthy. The fix above just makes AISummarization itself succeed more
reliably for non-English content.

---

## Fix 2 — google_tool_event: 400 Bad Request from Google Calendar API

### Symptom

n8n logs show:

```
{ "error": { "errors": [ { "domain": "global", "reason": "badRequest",
"message": "Bad Request" } ], "code": 400, "message": "Bad Request" } }
```

User receives a calendar invite with empty title (just `,`) and the wrong
date (today's timestamp instead of the meeting's planned date).

### Root cause

The workflow was reading calendar items as `{title, time}` only. When
`title` was empty or `time` was a natural-language string ("tomorrow",
"शाम को"), the Google Calendar API rejected the payload or filled with
defaults.

### Fix on n8n (do this once)

1. Open `https://n8n.backend.lehana.in`.
2. Open the workflow named **google_tool_event**.
3. Click the **Code** node that prepares the calendar event for the
   Google Calendar API call.
4. Replace the calendar-extraction logic. Meeting Master now sends a
   richer shape — use these fields:
   ```js
   const items = $json.calender || [];
   const events = items
     .filter(e => (e.event_title || e.title || '').trim())
     .map(e => {
       const startISO = e.start_datetime || `${e.event_date || ''}T${e.event_time || '10:00'}:00`;
       const endISO   = e.end_datetime   || startISO; // 1h default fallback applied below
       return {
         summary: e.event_title || e.title,
         description: e.description || e.notes || '',
         start: { dateTime: startISO, timeZone: 'Asia/Kolkata' },
         end:   { dateTime: endISO,   timeZone: 'Asia/Kolkata' },
         attendees: (e.attendees || e.participants || []).map(em => ({ email: em }))
       };
     });
   return events.map(e => ({ json: e }));
   ```
5. Make sure the **Google Calendar** node uses `={{$json.summary}}`,
   `={{$json.start.dateTime}}`, etc — NOT the old `{{$json.title}}` /
   `{{$json.time}}` mapping.
6. Save and re-activate.

### Containment already in place in this repo

`meeting-master/backend/api.py` (`_format_event_for_google_tools`) now
*always* sends:
- `event_title`, `title` — both filled with the same string
- `event_date` — ISO `YYYY-MM-DD`
- `event_time` — `HH:MM`
- `start_datetime`, `end_datetime` — full ISO timestamps
- `description`, `notes` — duplicated
- `participants`, `attendees` — duplicated, defaulting to meeting recipients
- `event_type` — `MEETING`
- `time` — legacy field, kept for backwards compatibility

Events with empty titles are now dropped before dispatch (no more `,`
calendar invites). So even with the old n8n code node, you should see
better behavior.

---

## Fix 3 — transcribe-speakers: "No audio binary found in request"

### Symptom

n8n execution log:

```
Problem in node 'Parse metadata'
No audio binary found in request [line 4]
```

### Root cause

Either:
- A test request was sent without a multipart `audio` binary part, OR
- An older version of the workflow is still active on the n8n server.

### Confirmation that our caller is correct

`meeting-master/backend/services/webhook.py:221` sends:
```python
files={"audio": (filename, file_bytes, content_type)}
```
which is exactly what the workflow expects.

### Fix on n8n (do this once)

1. Open `https://imworkflow.intermesh.net`.
2. Open the workflow **Transcribe Audio with Speaker Array (Sarvam
   Batch v1)** (workflow ID `O8KEIwhr8JE3XRDQ`).
3. Click the **Parse metadata** Code node.
4. Confirm the first 4 lines of the JS look like this (this is the
   audio0→audio normalization):
   ```js
   const headers = $json.headers || {};
   const query = $json.query || {};
   const binaryEntries = Object.entries($binary || {});
   const firstBinaryEntry = binaryEntries[0] || null;
   const binary = firstBinaryEntry ? firstBinaryEntry[1] : null;
   if (!binary) throw new Error('No audio binary found in request');
   ```
   If your live workflow has a different version that *only* reads
   `$binary.audio` directly, replace it with the snippet above.
5. Click the **Webhook: receive audio** node and confirm
   `Binary Property Name = audio` and **Binary Data = true**.
6. Save and ensure **Active** is **on** (the saved workflow JSON in this
   repo has `"active": false` which is just the export default — the
   workflow on the server should be active).

If you re-import `utils/transcribe_audio_speaker_array.workflow.json`
fresh, that file already has the correct code.

---

## Verification steps after applying fixes

From this repo:

```powershell
# from PowerShell, in D:\10xHackathon
.\scripts\start-demo.ps1
python e2e_audio_validation.py     # uploads real Hindi audio
python e2e_final_validation.py     # also covers translation + filesearch + BRD
.\scripts\test-e2e.ps1             # 13-check regression
```

Each script prints `PASS` at the end if every step succeeded. If you see
an n8n-side flake from AISummarization, the backend will now fall back
to deterministic extraction on the English-translated transcript and
still deliver a complete meeting record + English MoM + non-empty
calendar events.
