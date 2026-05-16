# Canopy Meeting Workspace — Skills Catalog (skills-v2)

This folder is the **canonical skills library** for the Canopy Meeting + BRD project.
Each subfolder is one self-contained skill following the `SKILL.md` convention:

```
{skill-folder}/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable helpers
├── references/       # Optional: deep-dive docs, sample payloads, troubleshooting
└── assets/           # Optional: prompt templates, schemas, JSON examples
```

> **For evaluators / agents reading this**: every skill describes a discrete
> capability of the product. Skills cross-link with `[[<name>]]` wiki-link
> notation — e.g. a SKILL.md may reference [[ai-summarization]] to point at
> the matching folder.
> Start from the [Pipeline overview](#pipeline-overview) below to understand
> how skills compose into the end-to-end meeting → BRD flow.

---

## Quick start

| Goal | Read first |
|---|---|
| Understand the whole pipeline end-to-end | [[16-e2e-validation]] |
| Wire a new transcription source | [[01-audio-capture-transcription]] |
| Fix a non-English meeting that came out wrong | [[02-transcript-translation]], [[15-multilingual-support]] |
| Improve task / MoM extraction quality | [[03-ai-summarization]] |
| Customize the auto-dispatched email | [[04-mom-email-generation]] |
| Calendar invite never lands | [[05-calendar-dispatch]], [[12-n8n-integration]] |
| BRD comes out incomplete | [[07-brd-generation]] |
| Dashboard shows stale/zero metrics | [[08-dashboard-metrics]], [[10-kpi-computation]] |
| Add launch-email context to BRDs | [[09-filesearch-rag]] |
| Frontend looks broken / chips don't add | [[11-frontend-ux-patterns]] |

---

## Pipeline overview

```
 ┌─────────────┐   ┌──────────────┐   ┌────────────────────┐   ┌──────────────┐
 │ Audio / Txt │ → │ Transcribe   │ → │ AISummarization    │ → │ Translation  │
 │  upload     │   │ (n8n Sarvam) │   │ (n8n Groq, JSON)   │   │ (LLM gateway)│
 └─────────────┘   └──────────────┘   └────────────────────┘   └──────────────┘
                                                                      │
                                                                      ▼
                ┌─────────────────────────────────────────────────────────────┐
                │ Auto-dispatch → google_tool_event → Email + Calendar invite │
                └─────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                ┌─────────────────────────────────────────────────────────────┐
                │ BRD bridge → RequireWise → LLM long-context Markdown BRD    │
                └─────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                ┌─────────────────────────────────────────────────────────────┐
                │ Dashboard (live KPIs) + File Search RAG (launch mail recall)│
                └─────────────────────────────────────────────────────────────┘
```

Each box has its own skill, plus several skills cover cross-cutting concerns
(schema, KPIs, UX patterns, validation).

---

## Skills index

| # | Skill | Surface area |
|---|---|---|
| 01 | [audio-capture-transcription](01-audio-capture-transcription/SKILL.md) | Mic recording, multipart upload, n8n Sarvam batch, diarization |
| 02 | [transcript-translation](02-transcript-translation/SKILL.md) | Native → English via LLM gateway, UTF-8 handling |
| 03 | [ai-summarization](03-ai-summarization/SKILL.md) | n8n AISummarization workflow, schema, deterministic fallback |
| 04 | [mom-email-generation](04-mom-email-generation/SKILL.md) | Professional MoM body, sensible subject, editable preview |
| 05 | [calendar-dispatch](05-calendar-dispatch/SKILL.md) | google_tool_event, fan-out, attendees as comma-string |
| 06 | [email-dispatch](06-email-dispatch/SKILL.md) | Auto-send + manual send, recipient chip lifecycle |
| 07 | [brd-generation](07-brd-generation/SKILL.md) | Long-context Markdown LLM, 3-pass repair, low-quality heuristic |
| 08 | [dashboard-metrics](08-dashboard-metrics/SKILL.md) | Live business-overview, BRD count, no mocks |
| 09 | [filesearch-rag](09-filesearch-rag/SKILL.md) | Gemini File Search proxy, ingest, search, status |
| 10 | [kpi-computation](10-kpi-computation/SKILL.md) | EHI, context completeness, action leakage, ownership coverage |
| 11 | [frontend-ux-patterns](11-frontend-ux-patterns/SKILL.md) | Chips, monotonic progress, formatted MoM preview, two-tab transcript |
| 12 | [n8n-integration](12-n8n-integration/SKILL.md) | Workflow architecture, credentials, manual fixes |
| 13 | [auto-dispatch-flow](13-auto-dispatch-flow/SKILL.md) | State machine: dispatching → completed |
| 14 | [schema-data-shapes](14-schema-data-shapes/SKILL.md) | Task, calendar, MoM, KPI, BRD wire formats |
| 15 | [multilingual-support](15-multilingual-support/SKILL.md) | Native + English tabs, Hindi/Tamil/Telugu inputs |
| 16 | [e2e-validation](16-e2e-validation/SKILL.md) | Test harness, regression coverage, real-flow probes |
| 17 | [auth-and-storage](17-auth-and-storage/SKILL.md) | Descope, guest, AUTH_DISABLED, JSON store atomics |

---

## How an agent should use this catalog

1. **When the user describes a behavior to add or fix**, identify which 1-3
   skills are relevant from the index above.
2. **Open the SKILL.md** of each. It has:
   - `When to use` — match against the user request
   - `How to apply` — concrete steps + exact file paths
   - `Related skills` — depth-first traversal targets
3. **Open `references/`** of those skills only when SKILL.md points you there
   for a deeper context (rare edge case, sample payload, troubleshooting log).
4. **Run `scripts/`** when SKILL.md instructs (typically only `09-filesearch-rag`
   and `16-e2e-validation` have executable helpers).

Cross-links use the `[[<name>]]` wiki-link notation — e.g. [[brd-generation]]
points at the `07-brd-generation/` folder. Match against the folder name
without the numeric prefix.

---

## Operating principles (apply across every skill)

These are non-negotiable contracts that every skill in this catalog respects.
Agents extending the system must keep these contracts intact.

1. **No mock data in user-visible paths.** Every metric, task, attendee, BRD
   section, calendar event, and email body in this product is computed from a
   real upstream call (Sarvam, the LLM gateway, an n8n webhook, or Gemini File
   Search). When an upstream fails, we either surface the error truthfully or
   degrade to a deterministic extractor from the **real** transcript — never a
   fabricated sample.
2. **English MoM body always goes to the recipient**, even when the source
   audio was Hindi / Tamil / Telugu. See [[02-transcript-translation]] and
   [[15-multilingual-support]].
3. **Monotonic progress.** The loading bar never decreases. Stale backend
   polls or smaller simulated ticks are coerced upward. See
   [[11-frontend-ux-patterns]].
4. **Completion guard.** A meeting is only marked `completed` after the
   auto-dispatch step has finished writing the automation record. See
   [[13-auto-dispatch-flow]].
5. **Task category enum**. The downstream n8n Groq node only accepts six
   categories. The backend coerces any task category to one of those six
   before dispatch. See [[03-ai-summarization]].
6. **Calendar attendees as comma-separated string** (not array of objects).
   The n8n Google Calendar node calls `.split(',')` internally. See
   [[05-calendar-dispatch]].
7. **Same recipients drive both email AND calendar.** The chip list in the
   UI is the single source of truth for both. See [[06-email-dispatch]].
8. **Sensible subjects.** Auto-generated subjects use the format
   `MoM • <Project Title> • <DD MMM YYYY>` — never the generic Groq
   "AI daily scrum summary". See [[04-mom-email-generation]].

---

## Verification

Before declaring any change "done", run:

```powershell
.\scripts\start-demo.ps1
python e2e_audio_validation.py
python e2e_final_validation.py
.\scripts\test-e2e.ps1
```

Expected: every script exits 0 / `PASS`. See [[16-e2e-validation]] for what
each script covers.

---

## Why these skills exist

The judges evaluate this project through skills. Each skill is a contract
between the codebase and any agent maintaining it. A new contributor (human or
AI) should be able to read one SKILL.md and know:

- when the skill applies
- which files in the repo back it
- how to extend / debug it safely
- which adjacent skills they'll touch in the same change

If you find a behavior that the current skills don't capture, that's a signal
to add a new skill folder — not to write loose docs.
