---
name: multilingual-support
description: Accept meeting audio in Hindi, Tamil, Telugu, Bengali, Marathi, etc. and surface the result to the user in two tabs (English / Native). The MoM email body always goes out in English regardless of source language.
---

# Multilingual Support

## When to use this skill

- The user records or uploads audio in a non-English language and expects
  the system to handle it cleanly.
- The transcript looks correct in the Native tab but the English tab is
  empty.
- The MoM email body went out in Hindi instead of English.
- Adding support for a new Indic language not currently surfaced.

## How to apply

### Detection

`_looks_non_english(text)` in `meeting-master/backend/api.py`:

```python
_NON_LATIN_RE = re.compile(r"[^\x00-\x7F]")

def _looks_non_english(text: str) -> bool:
    if not text:
        return False
    sample = text[:2000]
    non_latin = len(_NON_LATIN_RE.findall(sample))
    return non_latin >= max(8, int(len(sample) * 0.03))
```

The 3% / 8-char threshold handles short transcripts and avoids false
positives from single emojis or named entities.

Frontend has a matching `App.looksNonEnglish(text)` for the two-tab toggle.

### Sarvam batch language model

The n8n transcribe-speakers workflow uses `model: saaras:v3` which
auto-detects Indic + English in one pass. `language_code: unknown` (our
default) lets Sarvam decide.

For forced routing, send header `X-Language: hi | en | ta | te | bn | ml | mr | kn | gu | pa`.

Sarvam batch v1 supports diarization with `with_diarization: true` for
all the above languages.

### Translation step

After AISummarization succeeds (or the fallback runs), the dispatch
flow calls `_ensure_english_translation(updates)` which:

1. Checks if `transcript_en` is already populated and English-looking.
2. If not, checks if `raw_transcript` looks non-English.
3. If yes, calls the brd-agent `POST /api/translate` endpoint
   (see [[02-transcript-translation]]).
4. Stores result in `transcript_en`; preserves original under
   `raw_transcript`.

Same flow ensures the MoM email body is English — see
[[13-auto-dispatch-flow]].

### Frontend two-tab transcript

`meeting-master/frontend/index.html`:

```html
<div class="transcript-language-tabs">
  <button class="lang-tab active" data-lang="en"     onclick="App.switchLang('en')">English</button>
  <button class="lang-tab"        data-lang="native" onclick="App.switchLang('native')" id="lang-tab-native">Native</button>
</div>
<div class="transcript-content">
  <div id="transcript-en"     class="transcript-text"></div>
  <div id="transcript-native" class="transcript-text hidden"></div>
</div>
```

`App.displayResults` populates both elements and **hides the Native tab**
when the source was already English. So an all-English meeting just
shows one "English" tab — no clutter.

The previous three-tab UI (English / हिन्दी / Hinglish) was collapsed to
two because:
- "Hinglish" is rarely a distinct meaningful render — usually English
  with some transliterated words.
- The two-tab model is simpler: "translated" vs "verbatim source".

## Languages we've tested with real audio

| Language | Sarvam support | Translation quality |
|---|---|---|
| Hindi (Devanagari) | ✅ excellent diarization | ✅ literal, faithful |
| English | ✅ native | n/a |
| Code-switching Hindi/English | ✅ correctly tags both speakers | ✅ keeps the English parts unchanged |

The audio.mp3 sample in this repo is a real Hindi sales call (~30 seconds,
357 KB) that exercises this entire path. See [[16-e2e-validation]].

## Failure modes

| Symptom | Cause |
|---|---|
| English tab is empty, Native has Hindi | Translation step failed; check brd-agent logs |
| English tab shows garbled mojibake (`à¤œà¥€`) | Terminal encoding issue in print() — actual stored value is clean UTF-8 |
| Translation hallucinates unrelated text | Gateway received ASCII-escaped JSON; see [[02-transcript-translation]] UTF-8 fix |
| MoM email arrives in Hindi | `_ensure_english_mail_body` didn't run; check dispatch state machine |

## Related skills

- [[01-audio-capture-transcription]] — Sarvam transcribes Indic audio
- [[02-transcript-translation]] — does the actual LLM translation
- [[11-frontend-ux-patterns]] — two-tab UI pattern
- [[13-auto-dispatch-flow]] — guarantees English MoM in outbound email
