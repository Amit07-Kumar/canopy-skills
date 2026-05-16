---
name: email-dispatch
description: Send the MoM email through two parallel paths — automatic dispatch after a meeting completes, and manual user-initiated send from the editor. Both paths drive recipients from the same chip list and feed the n8n google_tool_event webhook.
---

# Email Dispatch

## When to use this skill

- The MoM email is not arriving in inboxes / arriving twice / arriving
  with stale recipients.
- You need to add a recipient mid-flight and resend.
- You're investigating why a `dispatch_success: true` record didn't
  actually produce an inbox arrival (Google API failure modes).

## How to apply

### Two dispatch paths

```
                 ┌─ Path A: auto-dispatch (right after meeting completes)
                 │       _auto_dispatch_meeting_outputs(meeting_id, user)
                 │       ↓
recipient chips ─┤    POST /webhook/google_tool_event
                 │
                 └─ Path B: manual send (user clicks "Send MoM Email")
                         POST /api/v1/meetings/{id}/send-email
                         ↓
                      POST /webhook/google_tool_event
```

Both paths use the same google_tool_event webhook. See [[05-calendar-dispatch]].

### Path A — Auto-dispatch

`meeting-master/backend/api.py:_auto_dispatch_meeting_outputs`:

1. Collects recipients via `_collect_dispatch_recipients(meeting, stored_user)`.
   Order: meeting `attendee.email` → user email → guest hint.
2. Builds the professional MoM body via `_build_professional_mom_body`
   (see [[04-mom-email-generation]]).
3. Builds the calendar payload via `_build_google_tools_payload` with
   richshape and category coercion.
4. Calls `trigger_google_tools_webhook(recipients, calendar, tasks, mom)`.
5. Persists `automation.dispatch_success`, `automation.auto_sent_email`,
   `automation.auto_scheduled_calendar`, `automation.dispatched_at`,
   `automation.error` based on the webhook response.
6. Only AFTER this returns, the meeting status flips to `completed`.
   See [[13-auto-dispatch-flow]].

### Path B — Manual user send

`meeting-master/backend/api.py` → `POST /api/v1/meetings/{id}/send-email`:

- Body: `{subject, to, body, cc?}`.
- Reads recipients from the request (the frontend pulls them from the chip
  list via `App.getAttendeeChipEmails()`).
- Calls `trigger_email_send_webhook` with a single-event payload aimed at
  google_tool_event.
- On success, marks `mail.sent = true`, `mail.sent_at = <ISO>`, and copies
  recipients onto `automation`.

### Chip lifecycle (frontend)

`meeting-master/frontend/app.js`:

- `App.renderRecipientChips(emails)` — paints the chip pills into
  `#email-recipient-chips`. Dedupes by lowercase email.
- `App.addRecipientFromInput(event)` — fires on Enter / comma / Tab key.
  Validates each token against `/^[^\s@]+@[^\s@]+\.[^\s@]+$/`.
- `App.getAttendeeChipEmails()` — single source of truth for "who gets
  this MoM".
- `App.collectEditedData()` — copies chip emails to BOTH `meeting.mail.to`
  AND `meeting.calendar_events[*].attendees` so calendar invites include
  the same people as the email.

## Failure modes

| Symptom | Diagnosis |
|---|---|
| `dispatch_success: true` but no inbox | Google API accepted but recipient blocked/spam. Check Gmail "Sent" view of service account. |
| `dispatch_success: false`, error="Bad Request" | Calendar event had empty title; fixed by dropping in `_format_event_for_google_tools`. |
| `dispatch_success: false`, error contains "500: Error in workflow" | n8n workflow internal error. Open executions in n8n. |
| Email arrives with stale recipients | Auto-dispatch fired before chip list was finalized. Re-send via manual path with current chips. |
| "Recipient required" toast | Chip list is empty AND home attendees are empty AND user email is unset. |

## Verification

```powershell
# Auto-dispatch path
python e2e_audio_validation.py
# Manual send path (re-uses last meeting)
.\scripts\test-e2e.ps1
```

`test-e2e.ps1` step 12 ("Manual send email") exercises the manual path
against the audio meeting from step 6.

## Related skills

- [[04-mom-email-generation]] — produces the professional subject + body
- [[05-calendar-dispatch]] — same workflow, calendar branch
- [[11-frontend-ux-patterns]] — chip input UX
- [[13-auto-dispatch-flow]] — completion guard around auto path
- [[14-schema-data-shapes]] — mail dict shape
