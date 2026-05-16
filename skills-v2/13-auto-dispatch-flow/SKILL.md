---
name: auto-dispatch-flow
description: The state machine that runs after a meeting's content is computed but before it is marked completed. Builds the professional MoM body server-side, ensures English translation, dispatches via google_tool_event, and uses a "dispatching" transient stage so the UI never shows completed before automation persistence.
---

# Auto-Dispatch Flow (the completion guard)

## When to use this skill

- A meeting is showing `completed` in the UI but the email never arrived
  → race condition in the state machine.
- You need to add a new automation step (e.g., Slack notification) and
  want to preserve the completion guard.
- You're debugging why `automation.error` is populated but `mail.sent`
  is true.

## How to apply

### State machine

```
PROCESSING
  └─ stage = transcribing | reading_transcript    (audio || text)
  └─ stage = summarizing
  └─ stage = drafting_outputs
  └─ stage = translating         (only when source ≠ English)
  └─ stage = dispatching         ← entry to this skill
       │
       ├─ _ensure_english_mail_body(meeting, store)
       ├─ _collect_dispatch_recipients(meeting, stored_user)
       ├─ _build_professional_mom_body(meeting, recipients)
       ├─ _build_professional_mom_subject(meeting)
       ├─ persist updated mail.subject + mail.body + mail.body_native
       ├─ _build_google_tools_payload(meeting, recipients, ...)
       ├─ trigger_google_tools_webhook(...)        ← actual n8n call
       ├─ persist automation.{dispatch_success, auto_sent_email,
       │                      auto_scheduled_calendar, dispatched_at, error}
       └─ persist mail.{sent: true, sent_at: <ISO>}  (only on success)
COMPLETED
  └─ stage = completed, progress = 100
```

The transient `dispatching` stage exists so the UI never shows `completed`
before the automation record is persisted. Before this guard, the UI saw
`completed` immediately and the user clicked "Send MoM Email" before
the auto-dispatch finished, producing duplicate sends.

### Implementation

`meeting-master/backend/api.py`:

- `_auto_dispatch_meeting_outputs(meeting_id, stored_user, store=None)`:
  - Called from `process_meeting_task` (audio path) line ~2087, from
    `process_text_meeting` (text path) line ~2015, and from
    `POST /meetings/{id}/process` line ~2204.
  - Returns the updated meeting dict or `None` if the meeting isn't found.

- The caller wraps:
  ```python
  store.update_meeting(meeting_id, {
      "status": ProcessingStatus.PROCESSING.value,
      "processing_progress": 96,
      "processing_stage": "dispatching",
      "processing_message": "Dispatching follow-up email and calendar actions.",
  })
  await _auto_dispatch_meeting_outputs(meeting_id, stored_user, store=store)
  store.update_meeting(meeting_id, {
      "status": ProcessingStatus.COMPLETED.value,
      "processing_progress": 100,
      "processing_stage": "completed",
      "processing_message": "Your meeting is ready to review.",
  })
  ```

### Recipient resolution order

`_collect_dispatch_recipients(meeting, stored_user)`:

1. Every `attendee.email` field where email is non-empty.
2. `meeting.mail.to` (legacy seed from the upload form).
3. `stored_user.email` (the uploader's email).
4. `meeting.attendee_emails` (request-level seed).

Deduped (lowercase), empty strings filtered. If the result is empty,
the entire dispatch is short-circuited with `dispatch_success: false,
error: "No recipient emails available for auto-dispatch"`. No exception
is raised; the meeting still completes with the failure recorded.

### Failure isolation

If `trigger_google_tools_webhook` raises or returns `{success: false}`:

- `automation.dispatch_success = false`
- `automation.error = <upstream message>`
- `automation.dispatched_at = None`
- `mail.sent` stays `false`

The meeting still transitions to `completed`. The user sees the error in
the UI ("Auto-dispatch: Pending" in the KPI snapshot of the MoM email)
and can manually retry via the **Send MoM Email** button (see
[[06-email-dispatch]]).

### Translation hook

`_ensure_english_mail_body(meeting, store)` runs FIRST inside the dispatch
step. If the existing `mail.body` looks non-English (>3% non-ASCII), it
translates via the imllm gateway and replaces the body. Original
preserved under `mail.body_native`. This means recipients ALWAYS get an
English email even when the audio was Hindi. See [[02-transcript-translation]]
and [[15-multilingual-support]].

### Professional body override

After translation, the body is **overwritten** with
`_build_professional_mom_body(meeting, recipients)` (see
[[04-mom-email-generation]]). This is intentional — AISummarization's
default body is often a terse 2-liner. The professional builder uses
the same structured data but composes a full launch-mail-quality MoM.

## Related skills

- [[02-transcript-translation]] — English translation step before dispatch
- [[04-mom-email-generation]] — body composer
- [[05-calendar-dispatch]] — calendar branch
- [[06-email-dispatch]] — email branch + manual retry
- [[10-kpi-computation]] — `time_to_action_seconds` measured here
