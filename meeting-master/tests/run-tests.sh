#!/bin/bash
# Meeting Master Test Suite
# Run: ./run-tests.sh [api_key]

set -e

BASE_URL="${BASE_URL:-https://meeting.lehana.in}"
API_KEY="${1:-$OPENROUTER_API_KEY}"
MODEL="${MODEL:-google/gemma-3-27b-it:free}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ PASS${NC}: $1"; PASSED=$((PASSED + 1)); }
fail() { echo -e "${RED}❌ FAIL${NC}: $1"; FAILED=$((FAILED + 1)); }
warn() { echo -e "${YELLOW}⚠️  WARN${NC}: $1"; WARNINGS=$((WARNINGS + 1)); }
info() { echo -e "${BLUE}ℹ️  INFO${NC}: $1"; }
skip() { echo -e "${YELLOW}⏭️  SKIP${NC}: $1"; SKIPPED=$((SKIPPED + 1)); }

PASSED=0
FAILED=0
WARNINGS=0
SKIPPED=0

echo ""
echo "============================================"
echo "🧪 Meeting Master Test Suite"
echo "============================================"
echo "Base URL: $BASE_URL"
echo "API Key:  ${API_KEY:0:20}..."
echo "Model:    $MODEL"
echo "============================================"
echo ""

# ===========================================
# Test 1: Health Check
# ===========================================
info "Test 1: Health Check"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE_URL/health")
if [ "$HTTP_CODE" == "200" ]; then
    pass "Health endpoint returns 200"
else
    fail "Health endpoint returns $HTTP_CODE"
fi

# ===========================================
# Test 2: Guest Authentication
# ===========================================
info "Test 2: Guest Authentication"
AUTH_RESP=$(curl -s -X POST --max-time 10 "$BASE_URL/api/v1/auth/guest")
TOKEN=$(echo "$AUTH_RESP" | jq -r '.access_token // empty')
if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
    pass "Guest auth returns token"
else
    fail "Guest auth failed: $AUTH_RESP"
    echo "Cannot continue without token. Exiting."
    exit 1
fi

# ===========================================
# Test 3: Protected Endpoint Requires Auth
# ===========================================
info "Test 3: Auth Required on Protected Endpoints"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$BASE_URL/api/v1/meetings")
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ]; then
    pass "Protected endpoint requires auth (HTTP $HTTP_CODE)"
else
    fail "Expected 401/403, got $HTTP_CODE"
fi

# ===========================================
# Test 4: Auth with Token Works
# ===========================================
info "Test 4: Auth with Token"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/v1/meetings")
if [ "$HTTP_CODE" == "200" ]; then
    pass "Token authentication works"
else
    fail "Token auth failed with HTTP $HTTP_CODE"
fi

# ===========================================
# Test 5: Both Domains Work
# ===========================================
info "Test 5: Dual Domain Support"
LEHANA_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://meeting.lehana.in/health")
AIDHUNIK_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://meeting.aidhunik.com/health")
if [ "$LEHANA_CODE" == "200" ] && [ "$AIDHUNIK_CODE" == "200" ]; then
    pass "Both domains working (lehana.in + aidhunik.com)"
else
    fail "Domain mismatch: lehana.in=$LEHANA_CODE, aidhunik.com=$AIDHUNIK_CODE"
fi

# ===========================================
# Test 6: Invalid Token Rejected
# ===========================================
info "Test 6: Invalid Token Rejection"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    -H "Authorization: Bearer invalid-token-12345" \
    "$BASE_URL/api/v1/meetings")
if [ "$HTTP_CODE" == "401" ]; then
    pass "Invalid token correctly rejected"
else
    warn "Expected 401 for invalid token, got $HTTP_CODE"
fi

# ===========================================
# Test 7: AI Model Availability
# ===========================================
if [ -n "$API_KEY" ]; then
    info "Test 7: AI Model Availability ($MODEL)"
    AI_RESP=$(curl -s -X POST --max-time 30 "https://openrouter.ai/api/v1/chat/completions" \
      -H "Authorization: Bearer $API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"Say hello\"}], \"max_tokens\": 20}")
    
    if echo "$AI_RESP" | jq -e '.choices[0].message.content' > /dev/null 2>&1; then
        CONTENT=$(echo "$AI_RESP" | jq -r '.choices[0].message.content')
        pass "Model responding: ${CONTENT:0:30}..."
    else
        ERROR=$(echo "$AI_RESP" | jq -r '.error.message // "Unknown error"')
        fail "Model error: $ERROR"
    fi
else
    skip "Test 7: AI Model (no API key provided)"
fi

# ===========================================
# Test 8: System Prompt Support
# ===========================================
if [ -n "$API_KEY" ]; then
    info "Test 8: System Prompt Support"
    SP_RESP=$(curl -s -X POST --max-time 30 "https://openrouter.ai/api/v1/chat/completions" \
      -H "Authorization: Bearer $API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "model": "'"$MODEL"'",
        "messages": [
          {"role": "system", "content": "Reply only with OK"},
          {"role": "user", "content": "Test"}
        ],
        "max_tokens": 10
      }')
    
    if echo "$SP_RESP" | jq -e '.error' > /dev/null 2>&1; then
        ERROR_MSG=$(echo "$SP_RESP" | jq -r '.error.message')
        if [[ "$ERROR_MSG" == *"instruction"* ]] || [[ "$ERROR_MSG" == *"system"* ]]; then
            warn "System prompts NOT supported - code must merge into user message"
        else
            fail "System prompt error: $ERROR_MSG"
        fi
    else
        pass "System prompts supported"
    fi
else
    skip "Test 8: System Prompt (no API key)"
fi

# ===========================================
# Test 9: JSON Output Capability
# ===========================================
if [ -n "$API_KEY" ]; then
    info "Test 9: JSON Output Capability"
    JSON_RESP=$(curl -s -X POST --max-time 30 "https://openrouter.ai/api/v1/chat/completions" \
      -H "Authorization: Bearer $API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "model": "'"$MODEL"'",
        "messages": [{
          "role": "user", 
          "content": "Return ONLY this exact JSON, nothing else: {\"test\": \"hello\"}"
        }],
        "max_tokens": 100
      }')
    
    CONTENT=$(echo "$JSON_RESP" | jq -r '.choices[0].message.content // empty')
    if [ -n "$CONTENT" ]; then
        # Try to extract JSON (handle markdown code blocks)
        JSON_CONTENT=$(echo "$CONTENT" | sed 's/```json//g' | sed 's/```//g' | tr -d '\n' | xargs)
        
        if echo "$JSON_CONTENT" | jq -e . > /dev/null 2>&1; then
            pass "Model returns valid JSON"
        else
            warn "JSON may need extraction from: ${CONTENT:0:50}..."
        fi
    else
        fail "No content returned"
    fi
else
    skip "Test 9: JSON Output (no API key)"
fi

# ===========================================
# Test 10: Settings Endpoint
# ===========================================
info "Test 10: Settings Endpoint"
SETTINGS_RESP=$(curl -s --max-time 10 \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/v1/settings")
HTTP_CODE=$(echo "$SETTINGS_RESP" | jq -r 'if .provider then "200" else "error" end' 2>/dev/null || echo "error")
if [ "$HTTP_CODE" == "200" ] || [ "$HTTP_CODE" != "error" ]; then
    pass "Settings endpoint works"
else
    warn "Settings endpoint response: ${SETTINGS_RESP:0:100}"
fi

# ===========================================
# Summary
# ===========================================
echo ""
echo "============================================"
echo "📊 Test Summary"
echo "============================================"
echo -e "${GREEN}Passed:   $PASSED${NC}"
echo -e "${RED}Failed:   $FAILED${NC}"
echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
echo -e "${YELLOW}Skipped:  $SKIPPED${NC}"
echo "============================================"

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}❌ Some tests failed!${NC}"
    exit 1
else
    echo -e "${GREEN}✅ All critical tests passed!${NC}"
    exit 0
fi
