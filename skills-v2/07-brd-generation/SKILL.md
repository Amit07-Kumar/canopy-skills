---
name: brd-generation
description: Turn a real meeting (transcript + tasks + calendar + attendees + KPIs) into a 25–30 KB professional Business Requirements Document via the imllm LLM gateway. Long-context Markdown path is preferred over JSON-then-render. Three-pass repair recovers from LLM truncation.
---

# BRD Generation

## When to use this skill

- A product manager or stakeholder asks for a structured BRD from a real
  meeting conversation — they don't want to spend an hour writing it.
- The BRD is coming out incomplete (missing sections, truncated mid-paragraph).
- The BRD is too generic ("safe business dummy") and doesn't reflect the
  actual meeting context.
- You need to extend BRD generation to a new project type or template.

## How to apply

### Bridge: meeting-master → brd-agent

`meeting-master/backend/api.py` → `POST /api/v1/meetings/{id}/generate-brd`:

1. Receives `{filename}` from the frontend (slugified meeting title or
   user-provided).
2. Builds a rich BRD prompt via `_build_brd_generation_prompt(meeting)`
   that includes:
   - meeting title, date, attendees with emails
   - tasks with owners, due dates, priorities, context
   - calendar events with start/end times
   - KPIs (EHI, context completeness, etc.)
   - mail body (MoM)
   - automation status
3. Calls brd-agent's `POST /api/new-brd` with `{filename, text}`.
   Timeout 420s.

### BRD generator (brd-agent)

`brd-agent/backend/server.py:_generate_brd_with_llm`:

LLM gateway: `imllm.intermesh.net/v1/chat/completions`, model
`anthropic/claude-opus-4-6`, temperature 0.3, max_tokens 8000.

Two routing paths based on prompt length:

#### Long context (≥ 2500 chars) — preferred for real meetings

1. **First pass**: ask for the full BRD as Markdown directly. System
   prompt: *"You write complete enterprise BRDs in Markdown. Return only
   Markdown with the exact required heading structure."*
2. **Second pass (repair)**: if first pass missed required headings,
   ask: *"You repair incomplete BRDs. Return only polished Markdown with
   the exact required section structure."*
3. **Third pass (section-append)**: if still incomplete, ask only for
   the missing sections in canonical order with their full bodies, then
   stitch them onto the partial BRD. This recovers the most stubborn
   truncation cases without redoing 25k chars.

If all three fail, raise `RuntimeError("Rendered BRD is incomplete after
markdown generation: <missing sections>")`.

#### Short context (< 2500 chars)

JSON-render-repair chain (legacy). Less reliable for real meeting content.

### Required sections

A BRD must contain these section markers (`_missing_brd_markers`):

```
## 1. EXECUTIVE SUMMARY
## 2. BUSINESS OBJECTIVES
## 3. STAKEHOLDER ANALYSIS
## 4. FUNCTIONAL REQUIREMENTS
## 5. NON-FUNCTIONAL REQUIREMENTS
## 6. ASSUMPTIONS & CONSTRAINTS
## 7. DATA SOURCES & INTEGRATIONS
## 8. ARCHITECTURE OVERVIEW
## 9. OPEN CONFLICTS
## 10. CORRECTIONS & FALSE POSITIVES
## 11. CHANGE LOG
```

`_is_complete_brd(text)` returns True only when all 11 are present.

### Low-quality heuristic

`_looks_like_low_quality_brd` rejects:
- empty / < 1200 chars
- missing 2+ of `executive summary`, `functional requirements`, `non-functional requirements`
- contains 4+ literal `TBD` placeholders **unless** the doc is ≥ 4000 chars
  and has all three required markers (then TBD count tolerated).

This prevents skeletal placeholder docs from being accepted as "real BRDs".

### File search augmentation

If `FILE_SEARCH_API_BASE` is configured, `_augment_brd_text_with_file_search`
runs a RAG query on the BRD title + first 600 chars of context, retrieves
up to 8 hits (capped at 6000 chars total), and appends them as
`"Retrieved file-search context for BRD grounding"` to the prompt.
This is how ingested launch emails get pulled into the BRD.

See [[09-filesearch-rag]].

### Persistence

`brd-agent/backend/local_brds.json` is a list of records:
```json
[
  {
    "id": "...",
    "filename": "<slug>",
    "name": "<display name>",
    "content": "<full BRD markdown>",
    "source": "llm-agent" | "n8n",
    "preview": "<first 300 chars>",
    "updated_at": "<ISO>"
  }
]
```

Records with the same `filename` are replaced. New records are prepended.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `Rendered BRD is incomplete after markdown generation: ## 6. ...` | Two passes both missed sections | Third pass section-append usually recovers; if not, retry — LLM is non-deterministic. |
| BRD looks generic / "safe business dummy" content | Prompt context too thin | Ensure tasks/MoM/calendar are populated before calling generate-brd. |
| Persisted BRD has truncated tail | Hit max_tokens=8000 | Raise to 12000 or split into JSON sections. |
| `BRD_AGENT_LLM_API_KEY is not configured` | `.env` missing the key | Set in `D:\10xHackathon\.env` and restart brd-agent. |

## Verification

```powershell
# generate-brd via the bridge
curl -X POST http://127.0.0.1:5098/api/v1/meetings/<id>/generate-brd `
     -H "Content-Type: application/json" `
     -d '{"filename":"my-brd-slug"}'
```

Expected: HTTP 200 in 90–180 seconds, response body has
`{success: true, data: {response: {source: "llm-agent", data: {text: "<25k+ chars>"}}}}`.
The BRD is also persisted in `brd-agent/backend/local_brds.json`.

## Related skills

- [[03-ai-summarization]] — feeds structured MoM/Task/Calendar context
- [[09-filesearch-rag]] — pulls in launch email context for grounding
- [[08-dashboard-metrics]] — BRD count drives a dashboard metric
- [[14-schema-data-shapes]] — meeting & BRD wire formats
- [[16-e2e-validation]] — verifies BRD generation in every E2E run

## Reference materials

- [`assets/required-brd-sections.md`](assets/required-brd-sections.md) — canonical 11-section template
- [`assets/repair-prompt.md`](assets/repair-prompt.md) — third-pass section-append prompt
