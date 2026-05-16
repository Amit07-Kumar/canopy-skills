---
name: transcript-translation
description: Translate a non-English raw transcript (Hindi, Tamil, Telugu, etc.) into English using the imllm LLM gateway, with UTF-8 safe transport, so the meeting UI can always show a clean English tab.
---

# Transcript Translation

## When to use this skill

- The raw transcript from Sarvam contains Devanagari / Tamil / Telugu /
  Bengali / Arabic / etc. characters and you need to populate
  `transcript_en` for the UI's English tab.
- The auto-dispatched MoM email is going out in the native language and
  should be English instead.
- You're investigating why translation came back as a hallucination /
  unrelated content (Unicode mojibake on the gateway side).

## How to apply

### Backend translation endpoint (brd-agent)

- `brd-agent/backend/server.py` → `POST /api/translate`:
  - Accepts `{text, target_language="English", preserve_speaker_tags=True}`.
  - Calls `imllm.intermesh.net/v1/chat/completions` (model
    `anthropic/claude-opus-4-6`) with `temperature=0.0` for deterministic
    literal output.
  - **CRITICAL**: serializes the body with `json.dumps(payload,
    ensure_ascii=False).encode("utf-8")` and posts via
    `httpx.AsyncClient.post(url, content=body)`. Without this the gateway
    receives `\uXXXX` escapes and produces hallucinated translations like
    "courtroom dialogue" for sales-call audio.
  - Returns `{success, translated, model, target_language, source_language?}`.

### Meeting-master integration

- `meeting-master/backend/api.py`:
  - `_looks_non_english(text)` — heuristic: non-ASCII >= 3% of first 2000
    chars triggers translation.
  - `_translate_via_brd_agent(text)` — proxies to brd-agent's `/translate`.
    Returns `None` on failure (no placeholder).
  - `_ensure_english_translation(updates)` — idempotent helper called after
    summarization completes. Populates `updates["transcript_en"]` and
    adds a `warning` field tagging the translation pass.
  - Wired in both the audio webhook path (line ~2090) and the synchronous
    `/process-text` endpoint (line ~2000).

### Manual re-translate

- `POST /api/v1/meetings/{meeting_id}/translate` — force a fresh translation
  of an existing meeting's `raw_transcript`. Useful for repairing meetings
  that completed before the translation step was added.

### Frontend display

- `meeting-master/frontend/app.js` → `displayResults`:
  - Detects non-English raw via `looksNonEnglish()`.
  - Populates two tabs: **English** (translated) and **Native** (raw).
  - Hides the Native tab when source is already English.
  - See [[15-multilingual-support]] and [[11-frontend-ux-patterns]] for
    the two-tab UX.

## Common failures & root causes

- **Translation hallucinates content unrelated to the input** — gateway
  is receiving ASCII-escaped JSON (`ज`). Fix: use the `content=`
  parameter with explicit UTF-8 bytes, not `json=`.
- **Translation returns empty string** — LLM gateway returned 4xx; check
  `BRD_AGENT_LLM_API_KEY` in `.env`.
- **Meeting completed but `transcript_en` is null** — `_ensure_english_translation`
  wasn't called or `raw_transcript` was empty when it ran. Re-run via the
  manual endpoint above.

## Verification

```powershell
python D:\10xHackathon\test_translate.py
```

Expected output: Hindi input round-trips to a literal, faithful English
translation. Sample:
> `[Speaker 2]: जी सर। हाँ अभी कर लेते हैं सर...`
> → `[Speaker 2]: Yes sir. Yes, let's do it now sir...`

## Related skills

- [[01-audio-capture-transcription]] — where raw_transcript comes from
- [[15-multilingual-support]] — UI patterns for Native/English tabs
- [[04-mom-email-generation]] — ensures MoM body is also English
- [[03-ai-summarization]] — fallback path also translates speaker_map first

## Reference materials

- [`references/utf8-gateway-quirk.md`](references/utf8-gateway-quirk.md) — full debug log + fix
- [`references/translation-prompt.md`](references/translation-prompt.md) — exact system + user prompts used
