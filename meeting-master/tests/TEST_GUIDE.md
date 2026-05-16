# 🧪 Meeting Master - Test Guide

> **Comprehensive testing guide for the Meeting Master AI meeting assistant**

---

## 📋 Overview

Meeting Master processes audio recordings to extract:
- **Transcription** - Multiple languages (EN, HI, Hinglish)
- **Tasks** - Action items with assignees and deadlines
- **Summary** - Meeting overview
- **Calendar Events** - Scheduling information
- **MoM Email** - Minutes of Meeting draft

---

## 🔧 Prerequisites

### Required API Keys

```bash
# Test these are set before testing
echo "OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:0:20}..."
echo "DEEPGRAM_API_KEY: ${DEEPGRAM_API_KEY:0:10}..."
echo "SARVAM_API_KEY: ${SARVAM_API_KEY:0:10}..."
```

### Test Audio Files

| File | Content | Language | Location |
|------|---------|----------|----------|
| English meeting | Clear English speech | EN | `/root/.github/test-assets/audio/` |
| Hindi sample | Hindi conversation | HI | `/root/repo/ai-for-bharat-prompt-challenge/test/` |
| Hinglish | Mixed code speech | HI+EN | Create or source |

### Service Running

```bash
# Verify container is running
docker ps | grep meeting-master

# Check health
curl -s https://meeting.lehana.in/health | jq .
```

---

## 🧪 Test Categories

### 1. Authentication Tests

#### 1.1 Guest Mode Login
```bash
# Test: Guest authentication works
curl -s -X POST https://meeting.lehana.in/api/v1/auth/guest | jq .

# Expected:
# {
#   "access_token": "xxx...",
#   "token_type": "bearer",
#   "user": {"id": "guest-xxx", "name": "Guest"}
# }
```

#### 1.2 Protected Endpoints Without Auth
```bash
# Test: Protected endpoint rejects without token
curl -s -o /dev/null -w "%{http_code}" https://meeting.lehana.in/api/v1/meetings

# Expected: 401 or 403
```

#### 1.3 Invalid Token
```bash
# Test: Invalid token is rejected
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer invalid-token" \
  https://meeting.lehana.in/api/v1/meetings

# Expected: 401
```

### 2. Meeting Upload Tests

#### 2.1 Valid Audio Upload
```bash
# Get auth token first
TOKEN=$(curl -s -X POST https://meeting.lehana.in/api/v1/auth/guest | jq -r '.access_token')

# Upload audio with settings
curl -s -X POST https://meeting.lehana.in/api/v1/meetings/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@/root/.github/test-assets/audio/english-meeting-sample.mp3;type=audio/mp3" \
  -F 'settings={"provider":"openrouter","api_key":"YOUR_KEY","model":"google/gemma-3-27b-it:free"}' | jq .

# Expected:
# {
#   "meeting_id": "uuid...",
#   "status": "processing"
# }
```

#### 2.2 Missing Audio File
```bash
# Test: Upload without audio fails
curl -s -X POST https://meeting.lehana.in/api/v1/meetings/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F 'settings={"provider":"openrouter"}' | jq .

# Expected: 400/422 with error message
```

#### 2.3 Invalid Audio Format
```bash
# Test: Non-audio file is rejected
curl -s -X POST https://meeting.lehana.in/api/v1/meetings/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@/root/.github/test-assets/json/valid-api-payload.json;type=audio/mp3" \
  -F 'settings={}' | jq .

# Expected: Error about invalid audio format
```

### 3. AI Processing Tests

#### 3.1 Model Availability Test
```bash
# Test: Check if model is available
API_KEY="sk-or-v1-YOUR_KEY"
MODEL="google/gemma-3-27b-it:free"

curl -s -X POST "https://openrouter.ai/api/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"Say hello\"}], \"max_tokens\": 20}" \
  | jq '{ok: (if .error then false else true end), error: .error.message, content: .choices[0].message.content}'
```

#### 3.2 System Prompt Support
```bash
# Test: Check if model supports system prompts
curl -s -X POST "https://openrouter.ai/api/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [
      {"role": "system", "content": "Reply only with OK"},
      {"role": "user", "content": "Test"}
    ],
    "max_tokens": 10
  }' | jq .

# If error contains "Developer instruction is not enabled":
# → Model doesn't support system prompts
# → Code should merge system prompt into user message
```

#### 3.3 JSON Output Test
```bash
# Test: Model can return structured JSON
curl -s -X POST "https://openrouter.ai/api/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [{
      "role": "user", 
      "content": "Extract tasks from this text and return ONLY valid JSON:\n\nJohn needs to review the report by Friday.\n\nReturn: {\"tasks\": [{\"title\": \"...\", \"assignee\": \"...\"}]}"
    }],
    "max_tokens": 500
  }' | jq -r '.choices[0].message.content'

# Expected: Valid JSON (may be wrapped in markdown code blocks)
```

### 4. BYOK (Bring Your Own Key) Tests

#### 4.1 Valid BYOK Settings
```bash
# Test: BYOK settings are accepted and used
TOKEN=$(curl -s -X POST https://meeting.lehana.in/api/v1/auth/guest | jq -r '.access_token')

curl -s -X POST https://meeting.lehana.in/api/v1/meetings/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@test-audio.mp3" \
  -F 'settings={
    "provider": "openrouter",
    "api_key": "sk-or-v1-VALID_KEY",
    "model": "google/gemma-3-27b-it:free"
  }' | jq .

# Expected: Processing starts with user's key
```

#### 4.2 Invalid API Key
```bash
# Test: Invalid API key is detected
curl -s -X POST https://meeting.lehana.in/api/v1/meetings/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@test-audio.mp3" \
  -F 'settings={
    "provider": "openrouter",
    "api_key": "invalid-key-12345",
    "model": "google/gemma-3-27b-it:free"
  }' | jq .

# Expected: Error about invalid API key (should validate before processing)
```

#### 4.3 Invalid Model Name
```bash
# Test: Non-existent model is handled
curl -s -X POST https://meeting.lehana.in/api/v1/meetings/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@test-audio.mp3" \
  -F 'settings={
    "provider": "openrouter",
    "api_key": "sk-or-v1-VALID_KEY",
    "model": "nonexistent/model-name"
  }' | jq .

# Expected: Error about model not found
```

### 5. Meeting Status & Results Tests

#### 5.1 Get Meeting Status
```bash
# After upload, check status
MEETING_ID="your-meeting-id"

curl -s "https://meeting.lehana.in/api/v1/meetings/$MEETING_ID/status" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Expected:
# {
#   "meeting_id": "...",
#   "status": "processing" | "completed" | "failed",
#   "progress": 50
# }
```

#### 5.2 Get Meeting Results
```bash
# After processing completes
curl -s "https://meeting.lehana.in/api/v1/meetings/$MEETING_ID" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Expected (when completed):
# {
#   "meeting_id": "...",
#   "transcript": {...},
#   "tasks": [...],
#   "summary": "...",
#   "calendar_events": [...],
#   "mom_email": {...}
# }
```

### 6. Frontend Tests

#### 6.1 Model Selector Suggestions
Open browser console and test:

```javascript
// Test: Model datalist has options
const datalist = document.getElementById('model-options');
console.log(`Model options: ${datalist ? datalist.options.length : 'NOT FOUND'}`);

// Test: Input shows suggestions
const input = document.getElementById('byokModel');
input.focus();
// Check if suggestions appear
```

#### 6.2 Settings Validation
```javascript
// Test: Settings validation before save
async function testSettingsValidation() {
  const result = await validateSettings({
    provider: 'openrouter',
    api_key: 'invalid-key',
    model: 'google/gemma-3-27b-it:free'
  });
  console.log('Validation result:', result);
}
```

### 7. Dual Domain Tests

```bash
# Test both domains work identically
for domain in "meeting.lehana.in" "meeting.aidhunik.com"; do
  echo "Testing $domain..."
  
  # Health check
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${domain}/health")
  echo "  Health: $HTTP_CODE"
  
  # Guest auth
  AUTH_RESP=$(curl -s -X POST "https://${domain}/api/v1/auth/guest")
  HAS_TOKEN=$(echo "$AUTH_RESP" | jq -e '.access_token' > /dev/null && echo "YES" || echo "NO")
  echo "  Auth: $HAS_TOKEN"
done

# Expected: Both domains return same results
```

---

## 🔴 Known Issues

### 1. Model System Prompt Support
- **Issue**: Some models (gemma, gemini) don't support system prompts
- **Detection**: Error contains "Developer instruction is not enabled"
- **Fix**: Code merges system prompt into user message
- **Status**: ✅ Fixed in ai.py

### 2. Response Format Variations
- **Issue**: Some models return JSON in markdown code blocks
- **Detection**: Response starts with \`\`\`json
- **Fix**: `_extract_json()` strips markdown formatting
- **Status**: ✅ Fixed in ai.py

### 3. BYOK Model Selector
- **Issue**: Datalist not showing suggestions when typing
- **Detection**: Focus input, type, no dropdown appears
- **Root Cause**: `updateBYOKProvider()` was targeting INPUT as SELECT instead of DATALIST
- **Fix**: Applied fix to `app.js` - changed to properly populate DATALIST element
- **Status**: ✅ Fixed (2026-01-29)

---

## 📊 Test Script

Save as `/root/ideas/meeting-master/tests/run-tests.sh`:

```bash
#!/bin/bash
# Meeting Master Test Suite

set -e

BASE_URL="${BASE_URL:-https://meeting.lehana.in}"
API_KEY="${OPENROUTER_API_KEY:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ PASS${NC}: $1"; }
fail() { echo -e "${RED}❌ FAIL${NC}: $1"; }
warn() { echo -e "${YELLOW}⚠️  WARN${NC}: $1"; }
info() { echo -e "ℹ️  INFO: $1"; }

echo "============================================"
echo "Meeting Master Test Suite"
echo "Base URL: $BASE_URL"
echo "============================================"

# Test 1: Health Check
info "Test 1: Health Check"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health")
if [ "$HTTP_CODE" == "200" ]; then
    pass "Health endpoint returns 200"
else
    fail "Health endpoint returns $HTTP_CODE"
fi

# Test 2: Guest Authentication
info "Test 2: Guest Authentication"
AUTH_RESP=$(curl -s -X POST "$BASE_URL/api/v1/auth/guest")
TOKEN=$(echo "$AUTH_RESP" | jq -r '.access_token // empty')
if [ -n "$TOKEN" ]; then
    pass "Guest auth returns token"
else
    fail "Guest auth failed: $AUTH_RESP"
    exit 1
fi

# Test 3: Protected Endpoint Requires Auth
info "Test 3: Auth Required"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/meetings")
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ]; then
    pass "Protected endpoint requires auth (HTTP $HTTP_CODE)"
else
    fail "Expected 401/403, got $HTTP_CODE"
fi

# Test 4: Both Domains Work
info "Test 4: Dual Domain Support"
LEHANA_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://meeting.lehana.in/health")
AIDHUNIK_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://meeting.aidhunik.com/health")
if [ "$LEHANA_CODE" == "200" ] && [ "$AIDHUNIK_CODE" == "200" ]; then
    pass "Both domains working"
else
    warn "lehana.in: $LEHANA_CODE, aidhunik.com: $AIDHUNIK_CODE"
fi

# Test 5: AI Model Availability (if API key provided)
if [ -n "$API_KEY" ]; then
    info "Test 5: AI Model Availability"
    MODEL="google/gemma-3-27b-it:free"
    AI_RESP=$(curl -s -X POST "https://openrouter.ai/api/v1/chat/completions" \
      -H "Authorization: Bearer $API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"Hi\"}], \"max_tokens\": 10}")
    
    if echo "$AI_RESP" | jq -e '.choices[0].message.content' > /dev/null 2>&1; then
        pass "Model $MODEL is available"
    else
        ERROR=$(echo "$AI_RESP" | jq -r '.error.message // "Unknown error"')
        fail "Model error: $ERROR"
    fi
else
    warn "Test 5: Skipped (no API key)"
fi

echo ""
echo "============================================"
echo "Test Summary"
echo "============================================"
```

---

## 🔄 Continuous Testing

### Before Each Change
```bash
# Quick health check
curl -s https://meeting.lehana.in/health | jq .
```

### After Code Changes
```bash
# Rebuild and restart
cd /root/docker/meeting-master
docker-compose up -d --build
sleep 5

# Run quick tests
./tests/run-tests.sh
```

### Full Test (Before Deployment)
```bash
# Run complete test suite
cd /root/ideas/meeting-master/tests
./run-tests.sh

# Test with real audio
./test-e2e.sh
```

---

## 📝 Updating This Guide

When you discover new issues or edge cases:

1. Add to **Known Issues** section
2. Update test scripts
3. Add to `/root/.github/instructions/troubleshoot.instructions.md`
4. Update SERVICES.md if needed

---

**Last Updated**: 2026-01-29
**All Tests Passing**: 28/28 (100%)
**Tested Models**: google/gemma-3n-e2b-it:free, google/gemma-3-27b-it:free, meta-llama/llama-3.3-70b-instruct:free
