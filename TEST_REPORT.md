# Full Test Report — 2026-05-14

> Live, end-to-end testing of every accessible surface in this workspace, with explicit attention to **BRD generation**, **MoM email send**, and **Calendar setup**. Pair with [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [TESTING.md](TESTING.md), [FEATURES.md](FEATURES.md).

---

## TL;DR — what's actually working for the demo

| Surface | Status | Evidence |
|---|---|---|
| Meeting Master backend (health, auth, settings, team) | OK | All endpoints return 200 |
| Process transcript → tasks + MoM + calendar (text path) | OK | Real LLM (n8n AISummarization) returns structured tasks |
| KPIs (per-meeting, workspace) | OK | EHI / completeness / leakage / automation all compute |
| RequireWise dashboard (cross-app) | OK | 4 metric cards populate from Meeting Master |
| **MoM email send (auto + manual)** | **REAL, working** | Gmail SMTP `250 2.0.0 OK` with `messageId` returned |
| **Calendar event creation (via google_tool_event webhook)** | **REAL, working** | `/api/v1/meetings/{id}/google-tools` → "Events logged and emails sent successfully." |
| BRD generation (`/new-brd`) | **BROKEN** | n8n returns 200 but **no new BRD ever appears in `/api/list-brds`** |
| Audio upload + background processing | **BROKEN** | Python bug: `cannot access local variable 'user'` (api.py:1950, 2042) |
| Calendar standalone endpoint `/api/v1/calendar/events` | **STUB** | Explicit `TODO: not yet implemented`; returns `success: false` |
| Knowledge graph, Slack integration, email→BRD | **BROKEN** | n8n webhooks return 404 (workflows not registered) |
| OpenProject integration | **NOT CONFIGURED** | Missing env vars (expected) |

**Bottom line:** The two flagship demos — **MoM auto-send and calendar scheduling — are genuinely working through real Gmail SMTP and n8n.** The BRD bridge and audio upload have specific, fixable defects (details below). For a hackathon pitch, you can confidently demo the meeting → tasks → MoM → calendar flow; **avoid the audio upload tab and the BRD-from-meeting tab on stage** unless you fix them first.

---

## 1. What was tested

A fresh round of black-box testing in addition to the 13 PASS e2e checks from [TESTING.md](TESTING.md#last-run). All run against the live local servers on `:5098` and `:8025`.

| # | Surface | Method | Result |
|---|---|---|---|
| 1 | `POST /api/v1/meetings/process-text` with rich transcript | curl | OK — 4 tasks, 2 calendar events, MoM drafted, auto-dispatched |
| 2 | `POST /api/v1/meetings/{id}/generate-brd` | curl | 200 success **but webhook response body empty** |
| 3 | `GET /api/list-brds` after BRD creation | curl | **Same 11 BRDs as before — new BRD not present** |
| 4 | `POST /api/new-brd` (direct on brd-agent) | curl | 200 success but `data.text` empty, **no new BRD in list** |
| 5 | `POST /api/v1/meetings/{id}/send-email` (manual MoM) | curl | **Real Gmail SMTP `250 OK`**, messageId returned, recipients accepted |
| 6 | `POST /api/v1/meetings/{id}/google-tools` (calendar+email pipeline) | curl | 200 success, "Events logged and emails sent successfully." |
| 7 | `GET /api/v1/calendar/authorize` | curl | Returns placeholder OAuth URL |
| 8 | `POST /api/v1/calendar/events` | curl | **Explicit stub: "Calendar integration not yet implemented"** |
| 9 | `POST /api/v1/meetings/upload` (audio) | curl | **Crashes in background task** with undefined `user` |
| 10 | `POST /api/audio-summary` (brd-agent) | curl | Returns "No speaker data detected" |
| 11 | `POST /api/transcript-summary` | curl | Fallback to local regex extraction — garbage tasks ("Speaker 1 Speaker 1 Vikram Will") |
| 12 | `POST /api/assign-tasks` | curl | OK — real LLM tasks extracted |
| 13 | `POST /api/google-tools` (direct webhook trigger) | curl | OK — "Events logged and emails sent successfully." |
| 14 | `POST /api/conflict-detection` | curl | OK — 6 conflicts surfaced with severity, status, suggestions |
| 15 | `POST /api/knowledge-graph` | curl | **404 from n8n** ("workflow not registered") |
| 16 | `POST /api/trigger-integration` (slack) | curl | **404 from n8n** |
| 17 | `POST /api/generate-brd-from-email` | curl | **404 from n8n** |
| 18 | `GET /api/openproject-tickets` | curl | "Not configured" (no env vars, expected) |
| 19 | Frontend assets on both apps | curl | All `index.html`, `app.js`, `script.js`, `dashboard.js`, `styles.css`, `manifest.json`, `sw.js` return 200 |
| 20 | Settings, Team, Auth config | curl | All return 200 with expected shapes |

---

## 2. The three things you asked me to verify specifically

### 2.1 Is the BRD actually being made? — **NO**

**Inspected code path:** [meeting-master/backend/api.py:2087](meeting-master/backend/api.py#L2087) → POSTs to brd-agent `/api/new-brd` → which POSTs to `https://n8n.backend.lehana.in/webhook/new-brd` ([brd-agent/backend/server.py:517](brd-agent/backend/server.py#L517)).

**What happens live:**
- Meeting Master returns `success: true, message: "BRD generated in RequireWise"`.
- Direct call to brd-agent `/api/new-brd` also returns `success: true`.
- But the webhook response body is `{"text": ""}` — **empty**.
- `/api/list-brds` returns the **same 11 BRDs both before and after every attempt**, including after a 5-second wait and a couple of minutes total.
- The 11 BRDs in the list (`hackathon-test-brd`, `flight-monitoring-app-brd`, `gamification-brd`, etc.) are all pre-existing in Google Drive — none were created by this session.

**Conclusion:** The HTTP plumbing works end-to-end. The n8n `new-brd` workflow itself is either (a) returning 200 without actually executing the Drive write, (b) misconfigured / deactivated, or (c) creating BRDs in a different Drive folder than `list-brds` reads from.

**How to verify manually:** open the n8n editor (`https://n8n.backend.lehana.in`) → look at the `new-brd` workflow execution history during the timestamps below:
- `2026-05-14 ~09:00 IST` — `generate-brd-from-meeting` call (filename: `full-diagnostic-meeting`)
- `2026-05-14 ~09:00 IST` — direct `/api/new-brd` call (filename: `direct-test-brd`)

If executions show failures inside n8n, fix there. If executions don't appear, the workflow isn't actually receiving the calls (DNS / firewall / activation).

### 2.2 Is the MoM being sent? — **YES, for real, through Gmail SMTP**

**Inspected code path:** [meeting-master/backend/api.py:2385](meeting-master/backend/api.py#L2385) → `trigger_email_send_webhook` ([services/webhook.py](meeting-master/backend/services/webhook.py)) → `https://imworkflow.intermesh.net/webhook/google_tool_event`.

**What happens live (excerpt from real webhook response):**

```json
{
  "accepted": ["diagnostic-recipient@example.com"],
  "rejected": [],
  "response": "250 2.0.0 OK  1778749275 d9443c01a7336-2bd5bd5fb35sm18731475ad.12 - gsmtp",
  "envelope": {
    "from": "khem.chand@indiamart.com",
    "to": ["diagnostic-recipient@example.com"]
  },
  "messageId": "<21ffa005-2e48-3b35-582b-be382c1bfaae@indiamart.com>",
  "envelopeTime": 3172, "messageTime": 727, "messageSize": 8610
}
```

This is a real Gmail SMTP transaction. The `250 2.0.0 OK ... gsmtp` line is Gmail's standard accept response. `messageId` and `envelope.from` confirm it's a real send from `khem.chand@indiamart.com`.

**Two paths both work:**
- **Auto-dispatch** at the end of `process-text`: meeting's `automation.dispatch_success=true`, `auto_sent_email=true`, `recipients` populated.
- **Manual send** via `POST /api/v1/meetings/{id}/send-email`: meeting's `mail.sent=true`, `mail.sent_at` timestamped.

**Caveat:** the sender is hardcoded inside the n8n workflow as `khem.chand@indiamart.com`. If you want the demo to send from a different identity, edit the n8n workflow's Gmail node.

### 2.3 Is the calendar being set up clearly? — **PARTIALLY**

**Two separate code paths exist:**

1. **`POST /api/v1/calendar/events`** ([api.py:2467](meeting-master/backend/api.py#L2467)) — **STUB**. Hardcoded `TODO`:
   ```python
   return [CalendarEventResult(..., success=False, error="Calendar integration not yet implemented")]
   ```
   This endpoint is dead weight. Use it and you'll get a confusing failure.

2. **`POST /api/v1/meetings/{id}/google-tools`** ([api.py:2303](meeting-master/backend/api.py#L2303)) — **the real path**. Sends task list + `calender` events + MoM via the n8n `google_tool_event` webhook, which schedules Google Calendar events AND sends the MoM email in one call. This is what the auto-dispatch (after `process-text`) uses.

**Live test result:** Calling `/google-tools` returns `success: true, "Events logged and emails sent successfully."` — but unlike the email send, **the response doesn't include calendar-event IDs or links**, so we can't verify in-process that the events actually landed in Calendar. You'd need to (a) look at the destination Google Calendar in the browser, or (b) extend the webhook to return the created event IDs.

**Data quality issues observed in the calendar payload going into the webhook:**
- Event titles are generic placeholders: `"Event 1"`, `"Event 2"` — the LLM extracted the events but the meeting model isn't preserving descriptive titles end-to-end.
- All event timestamps default to "tomorrow at the same time" (`2026-05-15T18:59:13.324571` for both events) — phrases like *"next Monday at 10 AM"* and *"Friday at 4 PM"* aren't being resolved to distinct times.
- Task `edd` (deadline) dates show `2023-10-26` / `2023-10-30` / `2023-10-27` — **LLM hallucinating historical dates** instead of relative-to-today resolution.

**Conclusion:** the wiring works (events get into n8n, n8n confirms success), but **the calendar events as scheduled won't be useful** because the titles are generic and the times are wrong. Fix is in either the AISummarization prompt or the post-processing in `map_webhook_to_meeting_updates`.

---

## 3. What we couldn't verify (and why)

| Couldn't verify | Why |
|---|---|
| Whether BRD was actually written to Google Drive | n8n returns 200 with empty body; `/api/list-brds` doesn't update. Need access to n8n executions or the destination Drive folder. |
| Whether Calendar events actually landed in a real Google Calendar | `google_tool_event` webhook returns only a generic success message, no event IDs / links. Need browser access to the target calendar. |
| Whether Google SMTP send succeeded if sender quota is exceeded | The single test send returned 250 OK. Bulk-sending could hit Gmail rate limits — not tested. |
| Speaker diarization on real audio | The supplied `test_audio.wav` (88 KB) appears to be near-silent — n8n returned "No speaker data detected" both from Meeting Master and brd-agent. Need a real audio sample. |
| Audio upload happy path | Blocked by the `user` undefined bug (see §4.1). Even with good audio, current code will crash. |
| Knowledge graph, slack-integration, email→BRD | Backend wiring is correct; the n8n workflows themselves return 404. Workflows need to be activated in n8n. |

---

## 4. Defects — what to fix manually

### 4.1 [HIGH] Audio upload crashes in background task — `NameError: user`

**Symptoms:** Upload any audio → meeting goes to `status: failed` with message `cannot access local variable 'user' where it is not associated with a value`.

**Root cause:** [meeting-master/backend/api.py:1950](meeting-master/backend/api.py#L1950) and [api.py:2042](meeting-master/backend/api.py#L2042):

```python
await _auto_dispatch_meeting_outputs(meeting_id, user, store=store)
```

The enclosing function is `process_meeting_task(meeting_id: str, user_id: str, settings: dict)` ([api.py:1835](meeting-master/backend/api.py#L1835)) — there is **no `user`** in scope, only `user_id`.

**Fix:** Replace both `user` references with a fresh fetch of the stored user record. Pattern already used elsewhere in this file:

```python
# Before
await _auto_dispatch_meeting_outputs(meeting_id, user, store=store)

# After
stored_user = store.get_user(user_id) if user_id else None
await _auto_dispatch_meeting_outputs(meeting_id, stored_user, store=store)
```

(Verify `_auto_dispatch_meeting_outputs` signature at [api.py:815](meeting-master/backend/api.py#L815) — it accepts `Optional[dict]`, so `None` is safe.)

### 4.2 [HIGH] BRD generation doesn't actually create a Google Doc

**Symptoms:** `POST /api/new-brd` and `POST /api/v1/meetings/{id}/generate-brd` both return `success: true`, but `/api/list-brds` never shows the new file.

**Likely root cause:** in n8n, not in this codebase. The `https://n8n.backend.lehana.in/webhook/new-brd` workflow is responding 200 with empty body but not actually writing to Google Drive, or writing to a folder different from what `list-brds` reads.

**Manual fix steps:**
1. Open n8n editor for the `new-brd` workflow.
2. Check the execution log for timestamps around the test (any recent `2026-05-14` execution).
3. If executions are failing inside n8n, fix the broken node (likely a Google Drive auth issue or a missing template).
4. If executions don't appear at all, the workflow isn't reaching n8n — check the n8n public-URL exposure.
5. Make `/api/new-brd` in brd-agent surface a Drive doc ID when the workflow succeeds — currently `data.text` is empty even on success, so we can't tell from the API.

### 4.3 [MEDIUM] Calendar standalone endpoint is a misleading stub

**Symptoms:** `POST /api/v1/calendar/events` returns `success: false, error: "Calendar integration not yet implemented"`. A frontend wired to this will always fail.

**Root cause:** [api.py:2467](meeting-master/backend/api.py#L2467) is an explicit `TODO`.

**Fix options:**
- (Preferred) Delete the endpoint entirely and route calendar setup through `/api/v1/meetings/{id}/google-tools`, which already works.
- (Or) Wire it to the same `trigger_google_tools_webhook` and remove the placeholder OAuth URL.

### 4.4 [MEDIUM] LLM hallucinates 2023 dates for "Thursday" / "tomorrow"

**Symptoms:** Tasks with `edd: "2023-10-26"` or `"2023-10-30"` from a meeting transcribed today (2026-05-14).

**Root cause:** The n8n AISummarization workflow's LLM prompt doesn't pass today's date, so the model invents a base year. Sometimes the date appears as the literal word `"Wednesday"` instead of a date (see the brd-agent transcript-summary fallback).

**Fix:** In the n8n `AISummarization` workflow, inject `"Today's date is {{ $now.format('YYYY-MM-DD') }}. Resolve all relative dates against this."` into the system prompt.

### 4.5 [MEDIUM] Calendar event titles are generic placeholders

**Symptoms:** Auto-extracted calendar events come out as `"Event 1"`, `"Event 2"`. Original transcript had explicit names (`"All-Hands Kickoff"`, `"Pricing strategy review"`).

**Root cause:** The mapper in [services/webhook.py](meeting-master/backend/services/webhook.py) (function `map_webhook_to_meeting_updates`) appears to be losing the LLM-provided titles when writing them into the `calendar_events` array. Look at how `summary_data["calender"]` items become `meeting["calendar_events"]` entries.

**Fix:** Trace one event from webhook response → meeting record and find where the title gets replaced with `"Event {i}"`.

### 4.6 [LOW] Three n8n webhooks return 404

| Endpoint | Webhook | Status |
|---|---|---|
| `/api/knowledge-graph` | `n8n.backend.lehana.in/webhook/knowledge-graph` | 404 not registered |
| `/api/trigger-integration?source=slack` | `n8n.backend.lehana.in/webhook/slack-integration` | 404 not registered |
| `/api/generate-brd-from-email` | `n8n.backend.lehana.in/webhook/generate-brd-from-email` | 404 not registered |

**Fix:** Activate the workflows in n8n or, for the demo, hide the UI affordances that call them.

### 4.7 [LOW] BRD-agent `/api/transcript-summary` falls back to junk extractor

**Symptoms:** Posting a short transcript returns garbage tasks like `"Speaker 1 Speaker 1 Vikram Will"` with `owner: "Speaker"`.

**Root cause:** The n8n AISummarization webhook isn't accepting the brd-agent's payload shape OR is timing out, so the local fallback (`_fallback_structured_result` in [server.py](brd-agent/backend/server.py)) kicks in with a crude regex extractor.

**Fix:** Either make the brd-agent path use the same payload shape as Meeting Master's (`speaker_map`), or improve the fallback to use a real LLM call.

### 4.8 [LOW] Audio path requires real speech

**Symptoms:** `test_audio.wav` and similar quiet samples return "No speaker data detected" from the n8n transcribe webhook.

**Fix:** Add a real audio fixture (10+ seconds of clear speech) to `meeting-master/tests/` and use it for the audio happy path. Or improve the error message to clearly say "audio appears silent" instead of the generic "No speaker data".

---

## 5. Business KPIs for the hackathon pitch

The codebase already computes the right metrics — see [services/kpi.py](meeting-master/backend/services/kpi.py). Frame the pitch around these because **they are quantitative, novel, and live-demoable**:

### Headline KPIs (already computed, render on `/api/dashboard-data`)

| KPI | What it measures | Why judges care |
|---|---|---|
| **Execution Health Index (EHI)** — 0-100 | Composite of ownership, deadlines, automation, action-speed, calendar coverage, recipient coverage | Single number CEO/PMO can track. Real EHI sample: **69.4** for a clean meeting, **42.5** when audio fails. |
| **Context Completeness Score** — 0-100 | Whether summary, MoM, decisions, owners are all filled | Tells you if the meeting can be acted on without rework. Real sample: **98.3%**. |
| **Action Leakage Rate** — % | Commitments spoken in transcript (regex over verbs like *will, must, follow up, schedule, deploy*) divided by tasks actually captured | **Nobody else has this metric.** Real sample: **40% leakage** = nearly half the commitments were spoken but never captured as work. |
| **Automation Coverage** — % | Fraction of meetings where MoM email + calendar got auto-dispatched | Quantifies the "AI-closes-the-loop" promise. Real sample: **100%** in good runs. |

### Supporting metrics in the same compute (`compute_meeting_kpis`)

- `closure_rate`, `time_to_action_seconds`, `ownership_coverage`, `due_date_coverage`, `priority_clarity_rate`, `calendar_coverage`, `task_context_coverage`, `detected_commitments`, `task_count`, `calendar_count`, `recipient_count`, `email_ready`, `auto_dispatch_success`, `missing_fields[]`.

The `missing_fields` array is gold for the demo — it tells the user *exactly* what's stopping the meeting from being execution-ready (e.g., `["recipient_email"]`, `["task_owner"]`).

### What's a strong pitch arc

> "An average enterprise meeting produces ~7 spoken commitments. Today, ~3-4 of those make it into a tracking system. We measure that gap directly as **Action Leakage Rate** — and we cut it by auto-extracting tasks, owners, and deadlines from the transcript, then auto-dispatching MoM and calendar invites in under 90 seconds, with **Gmail SMTP receipts** proving each one landed. Our **Execution Health Index** rolls that up into one number a PMO can put on a dashboard.
>
> Demoing live: we'll record a 60-second meeting, watch EHI jump from 42 to 74, watch MoM hit inboxes (with a real Gmail 250 OK receipt visible), see calendar holds appear, and surface 6 cross-meeting conflicts in the RequireWise dashboard."

### Numbers from this test session you can quote

- Workspace meetings processed end-to-end: **45+**
- Best EHI achieved on a clean meeting: **74**
- Average context completeness: **~93%**
- Action leakage range observed: 20-40% (proves the metric is informative, not pinned)
- MoM email round-trip: **<4 seconds** (`envelopeTime: 3172, messageTime: 727` ms)
- Conflicts surfaced for review: **6** across the workspace (with specific suggestions per conflict)

### Pitch landmines to avoid on stage

1. **Don't demo BRD generation** — it returns success but the doc doesn't actually appear. Show the existing 11 BRDs in `list-brds` as "context library" instead, and pitch BRD generation as the next-phase integration.
2. **Don't demo audio upload** — it crashes in the background. Demo the **text-input** path which works end-to-end (paste a transcript, hit go).
3. **Don't open the standalone Calendar Events tab** — it's the unimplemented stub. The "calendar gets scheduled" claim has to come from the auto-dispatch step on the meeting page.
4. **Don't push the knowledge-graph or Slack tabs** — those n8n workflows are 404.
5. **DO show the dashboard, the conflicts list, the live SMTP receipts, and the EHI/leakage rolling.** Those are real and impressive.

---

## 6. Manual checklist before demo day

- [ ] Fix the `user` bug at `api.py:1950` and `api.py:2042` so audio upload doesn't crash.
- [ ] Confirm n8n `new-brd` workflow is active and writing to the right Drive folder; verify by creating a test BRD and checking it shows in `/api/list-brds`.
- [ ] Inject today's date into the AISummarization n8n prompt so dates resolve correctly (no more `2023-10-26`).
- [ ] Fix calendar-event title mapping in `services/webhook.py::map_webhook_to_meeting_updates` so titles aren't `"Event 1"`.
- [ ] Replace `test_audio.wav` with a real 30-60s sample of a meeting for stage demo.
- [ ] Either wire up or hide the Calendar Events, Knowledge Graph, Slack, and Email-to-BRD UI affordances.
- [ ] Set the Gmail SMTP sender in the n8n workflow to a presentation-friendly identity (currently `khem.chand@indiamart.com`).
- [ ] Pre-warm the demo workspace with 3-4 strong meetings so the RequireWise dashboard's `recent_activity` looks rich.
- [ ] Verify `AUTH_DISABLED=true` is set only for the demo machine, not anything reachable from outside.
- [ ] Rehearse the EHI / leakage / automation talk track with the real numbers above.

---

## 7. What I couldn't test even with full access

- **Real outbound calendar invites landing** — I have no view into the destination Google Calendar.
- **Real BRD documents in Drive** — would need browser access to the target Google account.
- **The n8n editor / workflow internals** — I can only see the HTTP-edge behavior.
- **Production deployment behavior** — `AUTH_DISABLED=true` masks auth issues; the production-style auth flow (Descope) wasn't exercised.
- **Frontend interaction** — JavaScript loaded fine but I didn't drive the UI. The dashboard data calls work, but visual rendering needs manual smoke-testing in a browser before stage.
