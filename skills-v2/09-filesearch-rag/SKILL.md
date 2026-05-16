---
name: filesearch-rag
description: Index PDFs, emails, and plain text into Gemini File Search, then run natural-language RAG queries from anywhere in the product. Used to ground BRD generation in launch-mail history and to answer ad-hoc questions over the knowledge corpus.
---

# File Search (Gemini RAG)

## When to use this skill

- A user wants to ingest launch emails, PDFs, or notes so they're
  searchable later.
- BRD generation needs grounding context from prior launch docs.
- A PM asks a natural-language question over indexed content
  ("What is the launch SKU code for XMPP rollout?").
- Filesearch is configured but failing — diagnose status / ingest /
  search separately.

## How to apply

### Configuration

`.env`:
```
FILE_SEARCH_API_BASE=https://gemini-files.aidhunik.com/api
FILE_SEARCH_TIMEOUT_SECONDS=45
FILE_SEARCH_MAX_CONTEXT_CHARS=6000
```

Hosted at `https://gemini-files.aidhunik.com` (Express + @google/genai
SDK + Multer + Node 18). Backed by Gemini File Search vector store.
Default store: `ncert-rag-store-fixed`.

### Endpoints exposed by this product

| Endpoint | Layer | Purpose |
|---|---|---|
| `GET  /api/v1/filesearch/status` | meeting-master proxy | Configured? doc count? store name? |
| `GET  /api/v1/filesearch/documents` | meeting-master proxy | List all indexed docs |
| `POST /api/v1/filesearch/ingest-text` | meeting-master proxy | Ingest plain text as virtual .txt file |
| `POST /api/v1/filesearch/ingest-file` | meeting-master proxy | Multipart upload of a PDF/file |
| `POST /api/v1/filesearch/search` | meeting-master proxy | RAG query |

Each meeting-master endpoint proxies to brd-agent (port 8025), which in
turn proxies to `https://gemini-files.aidhunik.com/api`. The two-hop
indirection keeps secrets on the server (Gemini API key, base URL) and
lets the meeting UI hit a same-origin endpoint.

### Ingest text (e.g., an email body)

```http
POST /api/v1/filesearch/ingest-text
Content-Type: application/json

{
  "title":   "launch-email-execution-cmd-center-2026-05-22",
  "content": "Subject: ... \n\nHi team, we are launching ...",
  "topic":   "launch-emails"    (optional metadata)
}
```

Response: `{success: true, filename: "<sanitized>.txt", upstream: {...}}`.

The brd-agent wraps the text as a virtual `.txt` file via multipart and
forwards to Gemini's `/index` endpoint. The Gemini SDK auto-embeds and
makes the doc searchable in ~10–15 seconds.

### Ingest file (e.g., a PDF)

```http
POST /api/v1/filesearch/ingest-file
Content-Type: multipart/form-data

[file field: PDF, txt, md, docx]
```

### Search

```http
POST /api/v1/filesearch/search
Content-Type: application/json

{ "query": "What is the launch SKU code for Canopy Execution Command Center?" }
```

Response (HTTP 200, ~3–6s):

```json
{
  "answer": "The launch SKU code for the Canopy Execution Command Center is CECC-2026-LAUNCH-01. It is scheduled for a public launch on May 22.",
  "sources": [...]    // file references from the RAG store
}
```

### BRD grounding

`brd-agent/backend/server.py:_augment_brd_text_with_file_search` is called
automatically inside `/api/new-brd`:

1. Build a search query from `filename` (slug) + first 600 chars of meeting context.
2. Hit `/api/search` against the configured store.
3. Take up to 8 hits, capped at 6000 total chars.
4. Append as `"Retrieved file-search context for BRD grounding\nQuery: ...\n- hit 1\n- hit 2\n..."` to the LLM prompt.

This is how the BRD generator pulls in launch emails / prior decisions
automatically — no extra user step.

## Scripts shipped with this skill

[`scripts/ingest_launch_mails.py`](scripts/ingest_launch_mails.py) — batch-ingest
all PDFs under a folder and verify the document count went up. Used for
the LaunchMail/ archive (see [E2E run history](../16-e2e-validation/SKILL.md)).

```powershell
python D:\10xHackathon\skills-v2\09-filesearch-rag\scripts\ingest_launch_mails.py
```

## Quota awareness

Gemini File Search free tier has a daily quota. When exhausted:

- **Ingest** → HTTP 200 (mostly — embedding queue is separate).
- **Search** → HTTP 429 with body `"You exceeded your current quota..."`.

The proxy surfaces this as HTTP 502 with the upstream message intact —
NOT a fake "no results" response. The frontend's filesearch panel shows
the real error text. Quota resets next UTC day.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `filesearch_documents_count: 0` after ingest | Embedding still in progress | Wait 10–20s, hit `/status` again |
| Search returns 502 with "quota" in body | Daily Gemini quota exhausted | Retry next day or upgrade tier |
| Search returns 200 but `answer` is empty | Doc not yet embedded OR query miss | Try a more specific query keyword |
| Ingest returns 502 | brd-agent down or `FILE_SEARCH_API_BASE` unset | Check `.env` and brd-agent health |

## Related skills

- [[07-brd-generation]] — consumes RAG hits for BRD grounding
- [[11-frontend-ux-patterns]] — sidebar filesearch panel UX
- [[14-schema-data-shapes]] — ingest payload shape
- [[16-e2e-validation]] — RAG smoke test in every E2E run
