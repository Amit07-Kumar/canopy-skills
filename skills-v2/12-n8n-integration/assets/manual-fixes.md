# n8n manual fix runbook — four common regressions

## Fix 1 — AISummarization rejecting `Other` category

**Symptom:** n8n execution log shows
```
tool call validation failed: parameters for tool format_final_json_response
did not match schema: errors: [/output/tasks/1/category: value must be one of
"Development", "Research", "Infra", "Bug", "Ops", "Documentation"]
```

**Fix:**

1. Open `https://imworkflow.intermesh.net/` → **AISummarization** workflow.
2. Click the **AI Scrum Assistant** (Groq) node.
3. Find the Output Parser / Response Format JSON schema.
4. Locate the `tasks[].category` definition:
   ```json
   "category": {
     "type": "string",
     "enum": ["Development", "Research", "Infra", "Bug", "Ops", "Documentation"]
   }
   ```
5. Loosen to:
   ```json
   "category": {
     "type": "string",
     "enum": ["Development", "Research", "Infra", "Bug", "Ops", "Documentation", "Other", "Meeting"],
     "default": "Ops"
   }
   ```
6. In the System prompt, replace the `TASK RULES` block with the version in
   `skills-v2/03-ai-summarization/assets/groq-system-prompt.txt`.
7. Save. Toggle Active OFF → ON.

---

## Fix 2 — google_tool_event returning 400 from Google Calendar API

**Symptom:** Google Calendar API responds
```
{"error": {"errors": [{"reason": "badRequest", "message": "Bad Request"}], "code": 400}}
```
User sees an empty-title (",") calendar invite or no invite at all.

**Fix:**

1. Open `https://n8n.backend.lehana.in/` → **google_tool_event** workflow.
2. Add a **Code in JavaScript** node between the Webhook and the
   **Create an event** node. Name it "Fan out calendar events".
3. Paste the canonical body from
   `skills-v2/05-calendar-dispatch/assets/fan-out-code.js`.
4. Connect: Webhook → Fan out → Create an event.
5. In **Create an event**, update field mappings:
   - Summary: `{{ $json.summary }}`
   - Start: `{{ $json.startISO }}`
   - End: `{{ $json.endISO }}`
   - Description (Additional): `{{ $json.description }}`
   - Attendees (Additional): `{{ $json.attendees }}`
6. Save. Toggle Active OFF → ON.

---

## Fix 3 — transcribe-speakers returning empty body in < 1 second

**Symptom:** `curl ... /webhook/transcribe-speakers` returns HTTP 200,
empty body, in ~0.3 seconds. Sarvam transcription takes 30–90s normally.

**Diagnosis:** Either the Webhook responseMode is wrong, OR a Sarvam
node errored very early (e.g., `access to env vars denied` because
`N8N_BLOCK_ENV_ACCESS_IN_NODE` is on at the server).

**Fix path A — response mode:**

1. Open the workflow → click **Webhook: receive audio** node.
2. Set **Response Mode** = "Using 'Respond to Webhook' Node".
3. Confirm a **Respond to Webhook** node exists at the END of the
   success branch (after `Respond downloaded JSON` / similar).

**Fix path B — Sarvam credentials:**

1. If Executions tab shows red on `Sarvam: create batch job` with
   `access to env vars denied`:
2. Create an n8n Header Auth credential named `Sarvam API` with
   `api-subscription-key: <fresh Sarvam key>`.
3. In each of the six Sarvam HTTP Request nodes:
   - Authentication → **Generic Credential Type** → **Header Auth** →
     pick `Sarvam API`.
   - DELETE the hardcoded `api-subscription-key` header row in the
     Headers section.
4. **Upload audio to signed URL** node — leave alone (uses Azure SAS,
   no Sarvam header).
5. Save. Toggle Active OFF → ON.

---

## Fix 4 — `attendee.split is not a function` on Create-an-event

**Symptom:** When the Create-an-event node fires, you see
```
Bad request - please check your parameters
Invalid attendee email.
```
n8n logs say `attendee.split is not a function`.

**Cause:** Create-an-event's **Attendees** field expects a comma-separated
**string** like `"a@x.com,b@y.com"`, NOT a JSON array of strings or
`{email}` objects. n8n internally does `attendees.split(',')` on the value.

**Fix:**

1. Open the Fan-out Code node (Fix 2 above) and confirm the `attendees`
   field is built as `emails.join(',')` (already in the canonical body).
2. In Create-an-event, **Attendees** must reference `{{ $json.attendees }}`
   directly — NOT wrapped in any array conversion.
3. Save. Toggle Active OFF → ON.

---

## Verification after applying any fix

```powershell
python D:\10xHackathon\probe_transcribe.py        # Fix 3 sanity
python D:\10xHackathon\probe_google_tools.py      # Fix 2 / 4 sanity
python D:\10xHackathon\e2e_audio_validation.py    # full chain
```

Expected: all probes return HTTP 200 with real payloads, audio E2E
completes with `dispatch_success: true`.
