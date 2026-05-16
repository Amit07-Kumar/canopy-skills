#!/usr/bin/env bash
# Smoke tests for the two Sarvam workflows.
# Usage:
#   SARVAM_API_KEY=sk_... N8N_BASE=https://imworkflow.intermesh.net bash utils/sarvam_test.sh
#
# Requires: bash, curl, jq (optional for pretty output).

set -e
: "${SARVAM_API_KEY:?Set SARVAM_API_KEY in env}"
N8N_BASE="${N8N_BASE:-https://imworkflow.intermesh.net}"
AUDIO="${AUDIO:-docs/fixtures/sample_meeting_audio.mp3}"

if [ ! -f "$AUDIO" ]; then
  echo "Audio fixture missing: $AUDIO" >&2
  exit 1
fi

echo
echo "=== 1. Direct Sarvam real-time STT (sanity check on API key) ==="
curl -sS -X POST https://api.sarvam.ai/speech-to-text \
  -H "api-subscription-key: $SARVAM_API_KEY" \
  -F "file=@$AUDIO" -F "model=saarika:v2.5" -F "language_code=unknown" \
  -w "\nHTTP=%{http_code}\n" | head -c 800

echo
echo "=== 2. n8n real-time chunked workflow ==="
curl -sS -X POST "$N8N_BASE/webhook/sarvam-realtime" \
  -H "X-Session-Id: smoke-$(date +%s)" \
  -H "X-Chunk-Index: 0" -H "X-Language: unknown" \
  -F "audio=@$AUDIO;type=audio/mpeg" \
  -w "\nHTTP=%{http_code}\n" | head -c 800

echo
echo "=== 3. n8n batch diarization workflow ==="
curl -sS -X POST "$N8N_BASE/webhook/sarvam-batch-diarize" \
  -H "X-Session-Id: smoke-batch-$(date +%s)" \
  -H "X-Language: unknown" \
  -F "audio=@$AUDIO;type=audio/mpeg" \
  --max-time 600 \
  -w "\nHTTP=%{http_code}\n" | head -c 1500

echo
echo "Done."
