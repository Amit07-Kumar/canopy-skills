---
name: schema-data-shapes
description: Canonical wire formats and Pydantic models for every data structure that flows through the product — Meeting record, Task, CalendarEvent, Mail, KPIs, Automation, BRD persisted record, google_tool_event payload, AISummarization response.
---

# Schema & Data Shapes

## When to use this skill

- You're writing code that produces or consumes one of these shapes
  and need the canonical fields.
- A field is missing in the UI and you need to trace which producer
  dropped it.
- You're adding a new persisted field — find where to declare it
  (Pydantic model + JSON store + Markdown documentation).

## Pydantic models

Defined in `meeting-master/backend/models.py`. Key enums:

```python
class ProcessingStatus(str, Enum):
    PENDING     = "pending"
    PROCESSING  = "processing"
    COMPLETED   = "completed"
    FAILED      = "failed"

class TaskCategory(str, Enum):
    # Legacy
    BUG           = "BUG"
    FEATURE       = "FEATURE"
    DOCUMENTATION = "DOCUMENTATION"
    MEETING       = "MEETING"
    OTHER         = "OTHER"
    # AISummarization six
    DEVELOPMENT   = "DEVELOPMENT"
    RESEARCH      = "RESEARCH"
    INFRA         = "INFRA"
    OPS           = "OPS"

class TaskPriority(str, Enum):
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"
    CRITICAL = "CRITICAL"

class TaskStatus(str, Enum):
    TODO        = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE        = "DONE"
    CANCELLED   = "CANCELLED"

class CalendarEventType(str, Enum):
    MEETING  = "MEETING"
    REMINDER = "REMINDER"
    DEADLINE = "DEADLINE"
```

## Meeting record

Stored in `meeting-master/data/store.json` under `meetings[<uuid>]`.
Returned by `GET /api/v1/meetings/{id}`:

```json
{
  "meeting_id":            "uuid",
  "user_id":               "user-id or guest-id or auth_disabled",
  "title":                 "string",
  "date":                  "ISO datetime",
  "duration_seconds":      "int or null",
  "audio_url":             "absolute file path or null",

  "status":                "pending | processing | completed | failed",
  "processing_progress":   "0..100",
  "processing_stage":      "queued | transcribing | summarizing | drafting_outputs | translating | dispatching | completed | failed",
  "processing_message":    "user-facing string",
  "error_message":         "string or null (only on failed)",

  "raw_transcript":        "speaker-tagged text in source language",
  "transcript_en":         "LLM-translated English (mirrors raw if source already English)",
  "transcript_hi":         "(legacy, unused)",
  "transcript_hinglish":   "(legacy, unused)",

  "attendees":             [Attendee, ...],
  "tasks":                 [Task, ...],
  "calendar_events":       [CalendarEvent, ...],
  "mail":                  Mail,
  "kpis":                  KPIs,
  "automation":            Automation,

  "summary":               "string OR structured dict (topic/discussion_summary/decisions/owner)",
  "tags":                  ["string", ...],
  "sentiment":             "string or null",
  "confidence":            "float or null",
  "warning":               "non-fatal warning string or null",

  "created_at":            "ISO",
  "updated_at":            "ISO",
  "processed_at":          "ISO of when processing finished",
  "model_used":            "n8n-webhook-pipeline | n8n-transcribe+local-summary-fallback | openrouter/<model> | ...",
  "processing_time_seconds": "float"
}
```

## Sub-shapes

### Attendee
```json
{
  "speaker_id":  "SPEAKER_1 | OPERATIONS_LEAD | RECIPIENT_1 | ...",
  "name":        "Display name (e.g., 'Speaker 2', 'Operations Lead')",
  "email":       "email or null",
  "identified":  "bool — did the AI confidently identify this speaker?",
  "hint":        "context string"
}
```

### Task
```json
{
  "id":              "TASK_001",
  "title":           "string",
  "description":     "string or null",
  "assignee":        "string or null",
  "priority":        "HIGH | MEDIUM | LOW | CRITICAL",
  "category":        "one of the TaskCategory enum",
  "status":          "TODO | IN_PROGRESS | DONE | CANCELLED",
  "due_date":        "YYYY-MM-DD or null",
  "deadline_source": "string (e.g., 'n8n webhook', 'transcript: kal tak')",
  "dependencies":    ["TASK_002", ...],
  "context":         "free-text"
}
```

### CalendarEvent
```json
{
  "id":               "CAL_001",
  "title":            "string (never empty — empty-title events are dropped at dispatch)",
  "description":      "string",
  "start_datetime":   "ISO datetime",
  "end_datetime":     "ISO datetime",
  "attendees":        ["email", ...] or [{"email": "..."}, ...],
  "source":           "string (e.g., 'n8n webhook — 2026-05-22')",
  "type":             "MEETING | REMINDER | DEADLINE",
  "google_event_id":  "string or null"
}
```

### Mail
```json
{
  "subject":     "string — format: 'MoM • <Title> • <DD MMM YYYY>'",
  "to":          ["email", ...],
  "cc":          ["email", ...],
  "body":        "Markdown — full professional MoM (see [[04-mom-email-generation]])",
  "body_native": "Markdown — original AISummarization body before translation/professionalization",
  "sent":        "bool",
  "sent_at":     "ISO or null"
}
```

### KPIs
See [[10-kpi-computation]] for the full field list and formulas.

### Automation
```json
{
  "dispatch_success":          "bool",
  "auto_sent_email":           "bool",
  "auto_scheduled_calendar":   "bool",
  "dispatched_at":             "ISO or null",
  "baseline_timestamp":        "ISO — when processing finished",
  "recipients":                ["email", ...],
  "source":                    "meeting-master-auto-dispatch | manual-email-send",
  "error":                     "string or null"
}
```

## google_tool_event payload

See [[05-calendar-dispatch]] and `skills-v2/05-calendar-dispatch/assets/payload-sample.json`.

## AISummarization response

See [[03-ai-summarization]] and `skills-v2/03-ai-summarization/assets/groq-system-prompt.txt`.

## BRD persisted record

Stored in `brd-agent/backend/local_brds.json` as a list:

```json
[
  {
    "id":         "string",
    "filename":   "kebab-case slug",
    "name":       "Display name (toSentenceCase of slug)",
    "content":    "full Markdown BRD, 25-30 KB",
    "source":     "n8n | llm-agent",
    "preview":    "first 300 chars",
    "updated_at": "YYYY-MM-DD HH:MM:SS"
  }
]
```

Records are matched and replaced by `filename`. New records prepended.
See [[07-brd-generation]].

## Filesearch ingest payload

```json
{
  "title":   "human-readable title",
  "content": "plain text body",
  "topic":   "optional metadata tag",
  "source":  "optional metadata tag (e.g., 'meeting-master-ui')"
}
```

Returns `{success, filename: '<sanitized>.txt', upstream: {...}}`.
See [[09-filesearch-rag]].

## Related skills

- All other skills consume one or more of these shapes — this is the
  reference catalog.
