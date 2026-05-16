---
name: calendar-dispatch
description: Send real Google Calendar invites via the n8n google_tool_event webhook. Fan out the calendar array into one Create-an-event call per item, pass attendees as a comma-separated string (NOT array), and drop empty-title events to avoid the famous ","-titled invite bug.
---

# Calendar Dispatch (google_tool_event)

## When to use this skill

- The user expects N calendar invites for N events in a meeting but only
  gets 1 (or 0, or an empty-comma-titled invite).
- The n8n workflow returns 400 "Bad Request" from Google Calendar API.
- The Create-an-event node throws `attendee.split is not a function`.

## How to apply

### Wire format we send to n8n

URL: `POST https://n8n.backend.lehana.in/webhook/google_tool_event`

```json
{
  "recipients": ["amit.kumar5@indiamart.com"],
  "calender": [
    {
      "event_title":    "Steering Review",
      "title":          "Steering Review",
      "event_date":     "2026-05-20",
      "event_time":     "15:00",
      "start_datetime": "2026-05-20T15:00:00",
      "end_datetime":   "2026-05-20T16:00:00",
      "description":    "...",
      "notes":          "...",
      "participants":   ["amit.kumar5@indiamart.com"],
      "attendees":      ["amit.kumar5@indiamart.com"],
      "event_type":     "MEETING",
      "time":           "15:00"
    }
  ],
  "Task": [...],
  "MOM":  [...]
}
```

Notes:
- `calender` is misspelled — matches n8n workflow convention.
- Every event field is duplicated under multiple key names (`event_title`/`title`,
  `description`/`notes`, `participants`/`attendees`) so the downstream workflow
  cannot lose fields no matter which key the Groq node or Code node reads.
- Events with empty `title` are **dropped** before send (see `_build_google_tools_payload`).

### Backend builder

`meeting-master/backend/api.py`:

- `_format_event_for_google_tools(event, recipients)` — produces one rich
  event dict. Returns `None` if title is empty (so it gets filtered out).
- `_build_google_tools_payload(meeting, recipients, ...)` — assembles the
  full payload, dropping empty events and coercing task categories
  (see [[03-ai-summarization]]).

### n8n workflow (manual setup required once)

The workflow has three nodes that matter:

1. **Webhook: receive POST** — entry point.
2. **Code: Fan out calendar events** — splits `body.calender` array into
   one item per execution, attaches `summary`, `start`, `end`,
   `description`, `attendees` (as comma-string).
3. **Create an event** — Google Calendar node, reads from the
   fanned-out item.

The Fan-out Code node body (canonical):

```js
const body = $json.body || $json;
const calendars = Array.isArray(body.calender) ? body.calender
                : Array.isArray(body.calendar) ? body.calendar : [];
const tz = 'Asia/Kolkata';
const recipients = Array.isArray(body.recipients) ? body.recipients : [];

const items = calendars
  .filter(c => (c && (c.event_title || c.title) || '').toString().trim())
  .map(c => {
    const startDate = c.event_date || (c.start_datetime ? c.start_datetime.slice(0, 10) : '');
    const startTime = c.event_time
      || (c.start_datetime && c.start_datetime.includes('T')
            ? c.start_datetime.split('T')[1].slice(0, 5)
            : '10:00');
    const startISO = c.start_datetime || `${startDate}T${startTime}:00`;

    let endISO = c.end_datetime;
    if (!endISO) {
      const d = new Date(startISO);
      if (!isNaN(d.getTime())) {
        d.setHours(d.getHours() + 1);
        endISO = d.toISOString().slice(0, 19);
      } else {
        endISO = startISO;
      }
    }

    // CRITICAL: attendees as comma-separated string, not array.
    // The Google Calendar node internally calls attendees.split(',').
    const emails = (Array.isArray(c.attendees) && c.attendees.length ? c.attendees
                  : Array.isArray(c.participants) && c.participants.length ? c.participants
                  : recipients)
      .map(em => typeof em === 'string' ? em : (em && em.email) || '')
      .filter(em => em);

    return {
      json: {
        summary: c.event_title || c.title,
        description: c.description || c.notes || '',
        startISO,
        endISO,
        attendees: emails.join(','),  // comma-string, not array
      },
    };
  });

return items;  // empty → downstream skipped
```

### Field mapping in the Create-an-event node

| Google Calendar field | Expression |
|---|---|
| Summary | `{{ $json.summary }}` |
| Start | `{{ $json.startISO }}` (datetime) |
| End | `{{ $json.endISO }}` (datetime) |
| Description (Additional) | `{{ $json.description }}` |
| Attendees (Additional) | `{{ $json.attendees }}` |

Saved canonical version: [`assets/fan-out-code.js`](assets/fan-out-code.js).

## Recipients chip integration

The `email-recipient-chips` element on the frontend is the single source
of truth for who gets the email AND who gets the calendar invite.
`App.collectEditedData()` copies the chip list into:

1. `mail.to` (sent to email)
2. `calendar_events[*].attendees` (sent to google_tool_event)

See [[06-email-dispatch]] for the chip lifecycle.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `attendee.split is not a function` | Sent `attendees` as `[{email: '...'}]` array | Send as comma-string instead |
| 400 Bad Request from Google API | Empty `summary` field | Drop empty-title events client-side |
| Only 1 invite when 3 events were extracted | Create-an-event node hardcoded `Task[0]` | Add Fan-out Code node before it |
| Wrong date / today's timestamp | `start_datetime` was a natural language string ("tomorrow") | Provide ISO format + send `event_date` redundantly |
| "Invalid attendee email" on Execute step | Manual node test in n8n editor uses stale input | Test end-to-end via real webhook, not in-editor |

## Verification

```powershell
python D:\10xHackathon\probe_google_tools.py
```

Expected: HTTP 200, response JSON includes a real Google Calendar event
ID (`0r5if3hblsqf6vjf1kucbsa7ag` style) with `attendees: [{email: "...",
responseStatus: "needsAction"}]`.

## Related skills

- [[06-email-dispatch]] — same workflow, mom branch
- [[12-n8n-integration]] — Fan-out node + node wiring runbook
- [[11-frontend-ux-patterns]] — recipient chip input that feeds both email + calendar
- [[14-schema-data-shapes]] — calendar event shape

## Reference materials

- [`assets/fan-out-code.js`](assets/fan-out-code.js) — canonical Code node body
- [`assets/payload-sample.json`](assets/payload-sample.json) — full request shape
