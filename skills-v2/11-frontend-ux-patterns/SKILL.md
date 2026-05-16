---
name: frontend-ux-patterns
description: Frontend UX building blocks that make the product feel polished — chip-style multi-recipient input, monotonic progress bar, formatted MoM preview with Edit-Markdown toggle, two-tab transcript view, auto-switch to email tab on completion, and the unified Canopy portal navigation between MoM Workspace and BRD Studio.
---

# Frontend UX Patterns

## When to use this skill

- You're adding a new interactive surface (input, tab, panel) and need to
  follow the established patterns.
- Loading bar is "jumping backwards" — fix using the monotonic contract.
- Email body editor is locked / can't select-all — restore free editing.
- BRD page looks visually disconnected from MoM page — sync via the
  portal nav + shared backgrounds.

## How to apply

### 1. Chip-style multi-recipient input

The email recipients UX is a single-line "tag input" where:
- typing an email + Enter / comma / Tab adds a chip
- clicking × on a chip removes it
- pressing Enter on an empty input does nothing
- pasting `a@x.com,b@y.com c@z.com` adds all three at once

HTML skeleton:
```html
<div class="email-recipient-shell">
  <div id="email-recipient-chips" class="email-recipient-chips"></div>
  <input type="email" id="email-to-input"
         class="email-recipient-input"
         placeholder="Type an email and press Enter…"
         onkeydown="App.addRecipientFromInput(event)"
         onblur="if(this.value.trim()){App.addRecipientFromInput({key:'Enter',preventDefault:()=>{},target:this});}">
</div>
```

JS handlers (in `meeting-master/frontend/app.js`):
- `App.renderRecipientChips(emails)` — paint pills, dedupe lowercase.
- `App.addRecipientFromInput(event)` — fires on Enter/`,`/Tab, validates
  `^[^\s@]+@[^\s@]+\.[^\s@]+$` per token.
- `App.getAttendeeChipEmails()` — returns the current chip list.

**Single source of truth**: the chip list drives BOTH `mail.to` AND
`calendar_events[*].attendees` via `App.collectEditedData()`. Calendar
invites always include the same people as the email.

### 2. Monotonic progress bar

The loading overlay progresses through stages: uploading → preparing →
transcribing → summarizing → drafting → translating → dispatching → ready.

Contract: the displayed progress **never decreases**.

`updateLoadingProgress({progress, stageKey, message})` enforces:
```js
const nextValue = Math.max(0, Math.min(100, Math.round(progress)));
const prevValue = typeof activeFlow.progress === 'number' ? activeFlow.progress : 0;
activeFlow.progress = nextValue === 0 ? 0 : Math.max(prevValue, nextValue);
```

So a stale backend poll returning `progress: 28` after the simulated bar
already reached 31 is **silently coerced upward** to 31. The bar never
visually rewinds.

### 3. Status polling with wall-clock cap

`App.pollProcessingStatus(meetingId, startedAt)` is recursive setTimeout
at 1500ms intervals, but has a `PROCESSING_POLL_MAX_MS = 12 * 60 * 1000`
(12 min) wall-clock cap anchored to the first poll. After 12 min it shows
a user-friendly error: *"Processing timed out. Open the meeting from
history once it completes, or retry the upload."*

This prevents the modal from spinning forever if the backend goes silent.

### 4. Auto-switch to email tab on completion

`App.displayResults(meeting)` calls `this.switchResultsTab('calendar-email')`
at the end so users land on the email/calendar tab — the next action they
want to perform — instead of having to manually re-click away from the
transcript view.

### 5. Two-tab transcript (English / Native)

Replaced the original three tabs (English / हिन्दी / Hinglish) with two:
- **English** — translated via the LLM gateway (or the raw text when source
  is already English).
- **Native** — raw transcript verbatim; auto-hidden when source is English.

See [[15-multilingual-support]].

### 6. Formatted MoM preview + Edit Markdown toggle

Two views over the same email body:
- `#email-content-preview` — HTML rendered from the Markdown via
  `App.renderMarkdownToHtml(md)`. Default view.
- `#email-content` — `contenteditable=true`, raw Markdown source. User
  toggles via the "Edit Markdown" / "Preview" buttons (`App.setMomView`).

The editor has:
```css
.email-editor {
  user-select: text !important;
  cursor: text;
  min-height: 320px;
}
.email-editor:focus { outline: 2px solid var(--primary-500); }
```

This guarantees the user can select-all, copy, paste, and freely modify
the body. Default after the latest fixes is **edit mode** (was preview-locked).

### 7. Unified portal navigation

Both `meeting-master/frontend/index.html` and `brd-agent/frontend/index.html`
have the same header structure:

```html
<div class="portal-brand">
  <div class="portal-brand-mark">C</div>
  <div class="portal-brand-copy">
    <span class="portal-brand-eyebrow">Canopy Portal</span>
    <h1>Meeting Workspace</h1>  <!-- or "BRD Studio" -->
  </div>
</div>
<div class="portal-module-switch">
  <a id="portal-link-meetings" class="portal-module-pill is-active">MoM Workspace</a>
  <a id="portal-link-brd"      class="portal-module-pill">BRD Studio</a>
</div>
```

The "is-active" pill uses the same green gradient on both surfaces.
Backgrounds match (`#f4fbfa → #f7f4ed` cream gradient with subtle
green/orange tints). Tailwind dark mode disabled on BRD so the visual
transition feels seamless.

### 8. File validation on upload

`handleFileSelect(file)`:
- MIME prefix `audio/*` or `video/*` OR extension whitelist
  (mp3, m4a, webm, mp4, ogg, flac, opus, aac).
- Max size 100MB.

Substring matching (the old approach) over-matched and rejected
`audio/x-m4a`. The new dual-check (MIME OR ext) is robust.

### 9. Auth-Disabled prefill guard

When `AUTH_DISABLED=true` on the backend, the synthetic user has
`name: "Auth Disabled"`. The frontend explicitly suppresses this from
the Name input (`if (State.user.name && State.user.name !== 'Auth
Disabled') ...`). The input shows its real placeholder, not the
synthetic name.

## Related skills

- [[02-transcript-translation]] — feeds Native tab data
- [[04-mom-email-generation]] — body shown in preview
- [[06-email-dispatch]] — recipient chip lifecycle
- [[15-multilingual-support]] — two-tab transcript pattern
- [[17-auth-and-storage]] — AUTH_DISABLED user shape
