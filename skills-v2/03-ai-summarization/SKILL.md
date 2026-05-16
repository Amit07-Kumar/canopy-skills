---
name: ai-summarization
description: Turn a speaker-tagged transcript into structured MoM, tasks, and calendar events via the n8n AISummarization workflow (Groq-backed strict JSON schema), with a deterministic regex-based fallback when the upstream fails or returns invalid output.
---

# AI Summarization (transcript → MoM / Tasks / Calendar)

## When to use this skill

- You have a speaker_map (or plain transcript text) and need structured
  output: MoM bullets, tasks, calendar holds.
- The AISummarization webhook is returning errors or empty bodies and
  you need to understand the contract / fallback path.
- A task category like `"Other"` is hitting the strict enum validator
  in the downstream `google_tool_event` Groq node.

## How to apply

### n8n workflow contract

URL: `POST https://imworkflow.intermesh.net/webhook/AISummarization`

Request body: a JSON object keyed by speaker label.

```json
{
  "Speaker 1": "text...",
  "Speaker 2": "text..."
}
```

Response (HTTP 200, ~5–15s):

```json
[
  {
    "MOM":      [{"topic": "...", "discussion_summary": "...", "decisions": "...", "owner": "..."}],
    "Task":     [{"task_title": "...", "description": "...", "category": "Ops", "priority": "High", "edd": "2026-05-18"}],
    "calender": [{"event_title": "...", "event_type": "Scrum|MoM|Review|Demo|Call|Deadline", "event_date": "YYYY-MM-DD", "participants": [], "notes": "..."}]
  }
]
```

(Note the misspelling `calender` — preserved for n8n compatibility.)

The Groq AI Scrum Assistant node enforces a strict JSON schema with these
enums:

- `tasks[].category`: `Development | Research | Infra | Bug | Ops | Documentation` + tolerated `Other | Meeting` (after relax)
- `tasks[].priority`: `High | Medium | Low`
- `calendar[].event_type`: `Scrum | MoM | Review | Demo | Call | Deadline`
- All `*_date` fields: `^\d{4}-\d{2}-\d{2}$`, year forced to ≥ 2026.

### Backend caller

- `meeting-master/backend/services/webhook.py:summarize_transcript_webhook`:
  - Posts `speaker_map` as JSON body, 60s timeout.
  - Logs MOM/Task/Calendar counts on success.
  - Returns `{}` on non-200 or exception (NOT a placeholder dict).

### Mapping into the meeting record

- `services/webhook.py:map_webhook_to_meeting_updates`:
  - Normalizes MoM dict items into bullet strings.
  - `_normalize_task_item` extracts (title, description, priority, due_date).
  - `_safe_category(raw)` maps any n8n category string to the internal
    enum (BUG/FEATURE/DEVELOPMENT/RESEARCH/INFRA/OPS/DOCUMENTATION/MEETING).
    Anything unknown falls to `OPS` (never `OTHER` — see decision below).
  - Calendar events get `type` normalized to MEETING/REMINDER/DEADLINE.

### Deterministic fallback path

When `summary_data` comes back empty (AISummarization 5xx / quota / schema
failure), the system does **not** raise — it falls back to a deterministic
extractor:

- `meeting-master/backend/api.py:_fallback_process_transcript`:
  - Regex-based action-verb / commitment-cue extractor.
  - Runs on the **English-translated** transcript (translation happens
    BEFORE the fallback so the regex matches reliably).
  - Tags output with `model_used="n8n-transcribe+local-summary-fallback"`
    and a `warning` field so downstream code / UI knows this was degraded.

This means: even when AISummarization is down, the meeting still completes
with a non-empty MoM and at least one extracted task. No mock data — every
output is derived from real transcript content.

## Why we coerce categories

The downstream `google_tool_event` workflow's Groq node has a stricter
schema than AISummarization. It rejects any category outside the six allowed
values. To be robust to upstream drift:

1. `_safe_category` in `webhook.py` normalizes the **stored** category.
2. `_coerce_task_category` in `api.py` runs again at **dispatch** time before
   sending to google_tool_event.

Both layers apply the same alias map. See
[`assets/category-alias-map.json`](assets/category-alias-map.json).

## Manual n8n fix steps (one-time)

If the AISummarization workflow rejects valid-looking categories:

1. Open the AI Scrum Assistant node.
2. Loosen the `tasks[].category` schema enum to include `"Other"` and
   `"Meeting"` as accepted values.
3. Append to the system prompt: *"If a task does not clearly fit any of the
   first five, use 'Ops'. NEVER output 'Other' or any value outside the six
   above."*
4. Save. Toggle workflow Active OFF → ON.

See [[12-n8n-integration]] for the full manual fix runbook.

## Related skills

- [[01-audio-capture-transcription]] — produces the speaker_map input
- [[02-transcript-translation]] — runs after if source was non-English
- [[04-mom-email-generation]] — consumes MoM/Task/Calendar structured output
- [[12-n8n-integration]] — workflow schema fixes
- [[14-schema-data-shapes]] — canonical task/calendar shapes
