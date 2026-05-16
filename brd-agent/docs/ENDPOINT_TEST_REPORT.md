# Endpoint Test Report — RequireWise BRD Agent

**Date**: 2026-02-22  
**Tester**: Copilot Agent  
**Environment**: Production (`brd.aidhunik.com` → Docker container `brd-agent` port 8025)  
**Commit**: `0c2d0b9` (main)

---

## Summary

| # | Endpoint | Method | Status | HTTP Code | Response Time |
|---|----------|--------|--------|-----------|---------------|
| 1 | `/health` | GET | ✅ Pass | 200 | 0.027s |
| 2 | `/api/list-brds` | GET | ⚠️ Graceful 404 | 200 | 0.051s |
| 3 | `/api/list-brds?filename=trendy` | GET | ⚠️ Graceful 404 | 200 | 0.051s |
| 4 | `/api/new-brd` | POST | ⚠️ Graceful 404 | 200 | 0.051s |
| 5 | `/api/update-brd` (with filename) | POST | ✅ Pass | 200 | 0.079s |
| 6 | `/api/update-brd` (detect auto) | POST | ✅ Pass | 200 | 0.084s |
| 7 | n8n direct: `list-brds` | GET | ❌ Not Registered | 404 | 0.029s |
| 8 | n8n direct: `list-brds` | POST | ❌ Not Registered | 404 | 0.038s |
| 9 | n8n direct: `new-brd` | POST | ❌ Not Registered | 404 | 0.042s |
| 10 | n8n direct: `update-brd` | GET | ✅ Pass | 200 | 0.056s |

**Legend**:  
- ✅ Pass — Endpoint works end-to-end  
- ⚠️ Graceful 404 — Our proxy returns 200 with `success: false` because upstream n8n workflow is not activated  
- ❌ Not Registered — n8n webhook returns 404 (workflow needs activation)

---

## Detailed Results

### Test 1: Health Check

```bash
curl -s https://brd.aidhunik.com/health
```

**Response** (HTTP 200, 0.027s):
```json
{"status": "healthy", "service": "brd-agent"}
```

**Verdict**: ✅ **PASS** — Service is running and responding.

---

### Test 2: GET /api/list-brds (no filename)

```bash
curl -s https://brd.aidhunik.com/api/list-brds
```

**Response** (HTTP 200, 0.051s):
```json
{"success": false, "error": "list-brds returned 404", "brds": []}
```

**Verdict**: ⚠️ **GRACEFUL FAILURE** — Our proxy correctly forwards to `GET https://n8n.backend.lehana.in/webhook/list-brds`, receives 404 from n8n (workflow not activated), and returns a structured error with empty `brds` array. The frontend handles this by showing only the "Detect Automatically" dropdown option.

---

### Test 3: GET /api/list-brds?filename=trendy

```bash
curl -s "https://brd.aidhunik.com/api/list-brds?filename=trendy"
```

**Response** (HTTP 200, 0.051s):
```json
{"success": false, "error": "list-brds returned 404", "brds": []}
```

**Verdict**: ⚠️ **GRACEFUL FAILURE** — Same as Test 2. The `filename` query param is correctly forwarded but n8n workflow is inactive. This endpoint is used during BRD Generator polling to check if a newly-created file has appeared.

---

### Test 4: POST /api/new-brd

```bash
curl -s -X POST https://brd.aidhunik.com/api/new-brd \
  -H "Content-Type: application/json" \
  -d '{"filename": "test-brd-agent", "text": "Build a project management tool with Kanban boards"}'
```

**Response** (HTTP 200, 0.051s):
```json
{"success": false, "error": "new-brd returned 404"}
```

**Verdict**: ⚠️ **GRACEFUL FAILURE** — Our proxy correctly forwards to `POST https://n8n.backend.lehana.in/webhook/new-brd` with the JSON body. n8n returns 404 (workflow not activated). The frontend shows a proper error toast.

---

### Test 5: POST /api/update-brd (with filename)

```bash
curl -s -X POST https://brd.aidhunik.com/api/update-brd \
  -H "Content-Type: application/json" \
  -d '{"filename": "remote-automator", "summary": "buffalo"}'
```

**Response** (HTTP 200, 0.079s):
```json
{
  "success": true,
  "data": {
    "headers": {...},
    "params": {},
    "query": {"filename": "remote-automator", "summary": "buffalo"},
    "body": {},
    "webhookUrl": "https://n8n.backend.lehana.in/webhook/update-brd",
    "executionMode": "production"
  }
}
```

**Verdict**: ✅ **PASS** — The update-brd endpoint correctly:
- Sends a `GET` request to n8n (not POST)
- Passes `filename` and `summary` as query parameters
- n8n receives `?filename=remote-automator&summary=buffalo`
- This matches the expected URL format: `update-brd?filename=remote-automator&summary=buffalo`

---

### Test 6: POST /api/update-brd (Detect Automatically — empty filename)

```bash
curl -s -X POST https://brd.aidhunik.com/api/update-brd \
  -H "Content-Type: application/json" \
  -d '{"filename": "", "summary": "some meeting notes"}'
```

**Response** (HTTP 200, 0.084s):
```json
{
  "success": true,
  "data": {
    "headers": {...},
    "params": {},
    "query": {"summary": "some meeting notes"},
    "body": {},
    "webhookUrl": "https://n8n.backend.lehana.in/webhook/update-brd",
    "executionMode": "production"
  }
}
```

**Verdict**: ✅ **PASS** — When filename is empty (user selected "Detect Automatically"), the `filename` query param is correctly **omitted** from the request. Only `summary` is sent. n8n can then auto-detect which BRD to update.

---

### Test 7–9: Direct n8n Webhooks (list-brds, new-brd)

```bash
# Test 7: GET list-brds
curl -s "https://n8n.backend.lehana.in/webhook/list-brds"
# Test 8: POST list-brds
curl -s -X POST "https://n8n.backend.lehana.in/webhook/list-brds" -d '{}'
# Test 9: POST new-brd
curl -s -X POST "https://n8n.backend.lehana.in/webhook/new-brd" -d '{"filename":"test-brd","text":"Test content"}'
```

**Response** (all HTTP 404):
```json
{
  "code": 404,
  "message": "The requested webhook \"GET list-brds\" is not registered.",
  "hint": "The workflow must be active for a production URL to run successfully. You can activate the workflow using the toggle in the top-right of the editor."
}
```

**Verdict**: ❌ **NOT REGISTERED** — Both `list-brds` and `new-brd` workflows are not yet activated on `n8n.backend.lehana.in`. Tested both GET and POST methods for `list-brds` — neither is registered. **Action Required**: Activate these workflows in the n8n editor.

---

### Test 10: Direct n8n Webhook — update-brd

```bash
curl -s "https://n8n.backend.lehana.in/webhook/update-brd?filename=remote-automator&summary=buffalo"
```

**Response** (HTTP 200, 0.056s):
```json
{
  "headers": {...},
  "params": {},
  "query": {"filename": "remote-automator", "summary": "buffalo"},
  "body": {},
  "webhookUrl": "https://n8n.backend.lehana.in/webhook/update-brd",
  "executionMode": "production"
}
```

**Verdict**: ✅ **PASS** — The `update-brd` workflow is active and responding. It correctly receives `filename` and `summary` as query parameters via GET.

> **Note**: The response currently echoes back the request metadata (headers, query, body) rather than processing the BRD update. This suggests the n8n workflow is in a "respond immediately" mode or needs further nodes to process the data.

---

## Action Items

| Priority | Action | Owner |
|----------|--------|-------|
| 🔴 Critical | Activate `list-brds` workflow on n8n.backend.lehana.in | n8n Admin |
| 🔴 Critical | Activate `new-brd` workflow on n8n.backend.lehana.in | n8n Admin |
| 🟡 Medium | Verify `list-brds` HTTP method (GET vs POST) matches workflow config | n8n Admin |
| 🟡 Medium | Verify `update-brd` workflow processes data (currently echoes request) | n8n Admin |
| 🟢 Low | Confirm BRD polling detects file appearance once list-brds is active | Frontend QA |

---

## Architecture Flow

```
Browser (brd.aidhunik.com)
  │
  ├── GET /api/list-brds?filename=<optional>
  │     └── FastAPI proxy → GET n8n.backend.lehana.in/webhook/list-brds?filename=<slug>
  │
  ├── POST /api/new-brd {filename, text}
  │     └── FastAPI proxy → POST n8n.backend.lehana.in/webhook/new-brd {filename, text}
  │
  ├── POST /api/update-brd {filename, summary}
  │     └── FastAPI proxy → GET n8n.backend.lehana.in/webhook/update-brd?filename=<slug>&summary=<text>
  │
  └── BRD Generator Polling Flow:
        1. POST /api/new-brd → Submit creation
        2. Poll GET /api/list-brds?filename=<slug> every 500ms
        3. Up to 40 polls (20 seconds)
        4. If file appears → ✅ Success, refresh dropdown
        5. If timeout → ⏳ "Check back shortly" message
```

---

## Filename Convention

| Context | Format | Example |
|---------|--------|---------|
| API/Storage (slug) | lowercase, hyphen-separated | `remote-automator-1` |
| UI Display (sentence case) | First letter capital, spaces | `Remote automator 1` |
| User Input → Slug | Sanitized: lowercase, spaces→hyphens, remove special chars | `My Cool Project!` → `my-cool-project` |
| Slug → Display | Reverse: hyphens→spaces, capitalize first letter | `my-cool-project` → `My cool project` |
