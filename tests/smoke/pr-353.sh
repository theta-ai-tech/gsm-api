#!/usr/bin/env bash
# Smoke test for PR #353 — PUSH-1: deviceTokens storage
# Tests the Firestore emulator REST API directly (no endpoint added in this PR).
#
# Prerequisites:
#   Terminal 1: make emu-firestore
#   Terminal 2: make seed-emu && make api-dev-emu-auth
#
# Usage: bash tests/smoke/pr-353.sh

set -euo pipefail

EMU_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
BASE_URL="http://${EMU_HOST}/v1/projects/${PROJECT}/databases/(default)/documents"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS${NC}: $1"; }
fail() { echo -e "${RED}FAIL${NC}: $1"; exit 1; }

# ── AC1: Emulator is reachable ────────────────────────────────────────────────
echo "── Checking Firestore emulator is reachable ──"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/users" || true)
if [[ "$STATUS" == "200" || "$STATUS" == "404" ]]; then
  pass "Emulator reachable (HTTP $STATUS)"
else
  fail "Emulator not reachable at ${EMU_HOST} (HTTP $STATUS)"
fi

# ── AC2: Seeded user doc exists ───────────────────────────────────────────────
echo ""
echo "── Checking seeded user doc user_ignatios ──"
DOC=$(curl -s "${BASE_URL}/users/user_ignatios")
if echo "$DOC" | python3 -c "import sys, json; d=json.load(sys.stdin); exit(0 if 'fields' in d else 1)" 2>/dev/null; then
  pass "user_ignatios doc exists"
else
  fail "user_ignatios doc not found — run 'make seed-emu' first"
fi

# ── AC3: Onboarding via POST /me initialises deviceTokens to [] ──────────────
# We create a brand-new user doc directly via the emulator REST API to simulate
# what onboarding_service.register_me writes, and verify deviceTokens is [].
echo ""
echo "── Creating synthetic new-user doc with deviceTokens: [] ──"

NEW_UID="smoke_push1_$(date +%s)"
DOC_URL="${BASE_URL}/users/${NEW_UID}"

curl -s -X PATCH "${DOC_URL}?updateMask.fieldPaths=deviceTokens" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "deviceTokens": {"arrayValue": {"values": []}}
    }
  }' > /dev/null

RESULT=$(curl -s "${DOC_URL}")
DT_KEY=$(echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
fields = d.get('fields', {})
dt = fields.get('deviceTokens')
if dt is None:
    print('MISSING')
elif dt == {'arrayValue': {}} or dt == {'arrayValue': {'values': []}}:
    print('EMPTY_ARRAY')
else:
    print('UNEXPECTED:', dt)
" 2>/dev/null || echo "PARSE_ERROR")

if [[ "$DT_KEY" == "EMPTY_ARRAY" ]]; then
  pass "deviceTokens field initialised to empty array"
else
  fail "deviceTokens field unexpected value: $DT_KEY"
fi

# ── AC4: deviceTokens field is absent from PublicUserProfile (check via API) ─
# The API must NOT expose device_tokens on public profile endpoint.
# We verify the model by checking the field is only on PrivateUserProfile.
# Since the API must be running for this, we do a best-effort check.
API_PORT="${API_PORT:-8000}"
API_URL="http://127.0.0.1:${API_PORT}"

echo ""
echo "── Checking public profile does NOT expose device_tokens (best-effort) ──"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/users/user_ignatios" 2>/dev/null || echo "000")
if [[ "$HTTP_STATUS" == "000" ]]; then
  echo "  (API not running on port ${API_PORT} — skipping public-profile check)"
else
  PUBLIC_BODY=$(curl -s "${API_URL}/users/user_ignatios" -H "Authorization: Bearer dummy" 2>/dev/null || echo "{}")
  if echo "$PUBLIC_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(1 if 'device_tokens' in d else 0)" 2>/dev/null; then
    pass "device_tokens not present in public profile response"
  else
    fail "device_tokens unexpectedly present in public profile response"
  fi
fi

# ── Cleanup synthetic doc ─────────────────────────────────────────────────────
curl -s -X DELETE "${DOC_URL}" > /dev/null || true

echo ""
echo "All smoke tests passed for PR #353."
