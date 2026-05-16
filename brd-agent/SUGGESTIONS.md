# RequireWise BRD Agent — Improvement Suggestions

> Prioritized list of enhancements to make the BRD Agent more robust, useful, and hackathon-ready.

---

## 🔴 High Priority

### 1. Audio → Summary Pipeline (Two-Step Cross-Fill)

**Issue**: Recording output currently dumps raw speaker transcript into BRD fields. The transcript is useful for context but not structured enough for direct BRD generation.

**Plan**: After audio transcription, automatically run the AI Summarization step to produce MOM/Tasks/Calendar, THEN cross-fill the structured summary into BRD Generator and Update BRD fields.

**Flow**:
```
Record Audio → Transcribe (speaker text) → AI Summarize → Cross-fill structured output
                    ↓                            ↓
         Fill Meeting Transcript        Fill BRD Generator + Update BRD
```

**Effort**: Medium — chain the `/api/transcript-summary` call after audio transcription completes.

---

### 2. Activate N8N Workflows for list-brds, new-brd, view-brd

**Issue**: `list-brds` and `new-brd` n8n webhooks return 404 — workflows are not activated. The BRD Generator and Library features depend on these.

**Plan**: Activate the workflows in the n8n admin panel (`n8n.backend.lehana.in`). Verify each endpoint returns correct data.

**Effort**: Low — configuration only, no code changes needed.

---

### 3. Real-Time BRD Diff / Version Comparison

**Issue**: When updating a BRD, users can't see what changed. They send a summary and trust the AI handled it correctly.

**Plan**: After `update-brd` runs, fetch the updated BRD and show a before/after diff panel highlighting what the AI changed in the document.

**Effort**: High — requires storing previous BRD state and implementing a diff viewer.

---

## 🟠 Medium Priority

### 4. BRD Library — Direct Edit & Re-Generate

**Issue**: BRD Library currently only shows/views BRDs. Users should be able to select a BRD and re-generate or append requirements to it.

**Plan**: Add "Edit" and "Regenerate" buttons in the viewer panel. "Edit" loads content into the BRD Generator textarea. "Regenerate" re-submits to `new-brd` with merged content.

**Effort**: Medium.

---

### 5. Transcript Input → Auto-Detect Speaker Format

**Issue**: The Meeting Transcripter wraps all pasted text as "Speaker 1". If the transcript already has speaker labels (e.g., "John: ... \n Sarah: ..."), it should be parsed into multi-speaker JSON.

**Plan**: Add a regex parser that detects `Name:` patterns and builds a proper speaker-keyed payload for the AISummarization webhook.

**Effort**: Low — regex parsing in frontend before API call.

---

### 6. Task Assigner → BRD Cross-Fill (Bidirectional)

**Issue**: Tasks generated from the Task Assigner could feed back into BRD updates. Currently, task output doesn't flow back into BRD fields.

**Plan**: Add a "Send Tasks to BRD" button in the Task Assigner result panel. It compiles task list into structured text and cross-fills Update BRD summary.

**Effort**: Low — UI button + cross-fill logic (similar to existing patterns).

---

### 7. Persistent Project Context

**Issue**: Each session starts fresh. There's no memory of which BRDs were discussed, what changes were made, or what the user's preferences are.

**Plan**: Use `localStorage` to store:
- Last selected project
- Recent transcript summaries
- BRD update history (last 5 operations)
- User preferences (default recipients, preferred models)

**Effort**: Low — frontend-only, no backend changes.

---

### 8. Error Recovery for AISummarization 500s

**Issue**: The `AISummarization` workflow (on `imworkflow.intermesh.net`) intermittently returns 500 errors. The server falls back to mock data, which is misleading.

**Plan**: 
1. Show a clear "Using sample data — real AI summarization temporarily unavailable" warning banner
2. Add retry logic (3 attempts with exponential backoff)
3. Log failures to help debug the n8n workflow issue

**Effort**: Low-Medium.

---

## 🟢 Low Priority / Nice-to-Have

### 9. BRD Template Library

**Issue**: Users start from scratch every time. Common BRD structures (SRS, PRD, Technical Spec) could be pre-loaded.

**Plan**: Add a "Template" dropdown in the BRD Generator that pre-fills the textarea with a structured template (e.g., headings for Scope, Requirements, Acceptance Criteria, etc.).

**Effort**: Low — static templates in frontend config.

---

### 10. Keyboard Shortcuts

**Plan**: Add keyboard shortcuts for power users:
- `Ctrl+Enter` — Submit current form (generate BRD, summarize transcript, etc.)
- `Ctrl+R` — Start/stop recording
- `Ctrl+1/2/3` — Switch between Phase 1/2/Playground
- `Escape` — Close modals

**Effort**: Low.

---

### 11. Export BRD as PDF / Markdown

**Issue**: BRDs are stored in n8n's backend (likely Google Drive). Users may want a local copy.

**Plan**: Add "Export as Markdown" and "Export as PDF" buttons in the BRD Library viewer. Markdown export is trivial; PDF requires a library like `jsPDF` or server-side generation.

**Effort**: Medium.

---

### 12. Multi-Language Transcript Support

**Issue**: Transcription currently assumes English. Indian meetings often switch between Hindi and English.

**Plan**: Add a language selector for the transcription API. The Whisper model used by the n8n workflow can handle multilingual audio — just need to pass the language hint.

**Effort**: Low — add query parameter to audio upload.

---

### 13. Dashboard Metrics from Real Data

**Issue**: Phase 2 dashboard metrics (completion %, conflicts, stakeholders) come from mock/placeholder n8n webhooks.

**Plan**: Connect dashboard-data and conflict-detection endpoints to real Elasticsearch queries that aggregate BRD metadata (number of updates, open requirements, stakeholder mentions).

**Effort**: High — requires Elasticsearch indexing of BRD content.

---

### 14. Webhook Health Monitor

**Issue**: Several n8n webhooks are inactive (404) or broken (500), but the UI doesn't clearly indicate which features are available.

**Plan**: Add a health check on page load that pings each webhook and shows a status indicator (green/yellow/red dot) next to each feature card. Disabled features show a "Coming Soon" badge.

**Effort**: Medium.

---

### 15. Mobile-Responsive Layout

**Issue**: The bento grid layout is designed for desktop. On mobile, cards overlap and the recording button is hard to reach.

**Plan**: Add responsive breakpoints — stack cards vertically on mobile, reduce padding, make the recording button sticky at the bottom.

**Effort**: Medium — CSS-only changes.

---

## 📊 Priority Matrix

| # | Suggestion | Impact | Effort | Priority |
|---|-----------|--------|--------|----------|
| 1 | Audio → Summary Pipeline | High | Medium | 🔴 |
| 2 | Activate N8N Workflows | Critical | Low | 🔴 |
| 3 | BRD Diff/Version Compare | High | High | 🔴 |
| 4 | Library Edit & Regenerate | Medium | Medium | 🟠 |
| 5 | Auto-Detect Speakers | Medium | Low | 🟠 |
| 6 | Task → BRD Cross-Fill | Medium | Low | 🟠 |
| 7 | Persistent Context | Medium | Low | 🟠 |
| 8 | Error Recovery AISummarization | Medium | Low | 🟠 |
| 9 | BRD Templates | Low | Low | 🟢 |
| 10 | Keyboard Shortcuts | Low | Low | 🟢 |
| 11 | Export PDF/Markdown | Medium | Medium | 🟢 |
| 12 | Multi-Language Support | Low | Low | 🟢 |
| 13 | Dashboard Real Metrics | High | High | 🟢 |
| 14 | Webhook Health Monitor | Medium | Medium | 🟢 |
| 15 | Mobile Responsive | Medium | Medium | 🟢 |

---

*Last updated: Session 2026-07-09*
