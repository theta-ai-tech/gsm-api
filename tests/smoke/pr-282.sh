#!/usr/bin/env bash
# Smoke tests for PR #282: VEN-7 POST /venues/suggest (#164)
#
# Prerequisites:
#   Terminal 1: make emu-all
#   Terminal 2: make api-dev-emu-auth
#
# Optional overrides:
#   API_BASE_URL=http://127.0.0.1:8000
#   FIRESTORE_EMULATOR_HOST=127.0.0.1:8082
#   FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099
#   GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0
#
# Run from the gsm-api root or any worktree:
#   bash tests/smoke/pr-282.sh

set -uo pipefail

PASS=0
FAIL=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
API="${API_BASE_URL:-${GSM_API_URL:-http://127.0.0.1:8000}}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FS_EMU="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
FIRESTORE="http://${FS_EMU}/v1/projects/${PROJECT}/databases/(default)/documents"

export FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
export FIRESTORE_EMULATOR_HOST="$FS_EMU"
export GOOGLE_CLOUD_PROJECT="$PROJECT"

check() {
  local desc="$1" result="$2"
  if [ "$result" = "true" ]; then
    echo "  PASS: $desc"
    ((PASS++)) || true
  else
    echo "  FAIL: $desc"
    ((FAIL++)) || true
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ABORT: required command not found: $1"
    exit 1
  fi
}

http_code() {
  curl -sS -o /dev/null -w "%{http_code}" "$@"
}

document_count() {
  local collection="$1"
  curl -sS "$FIRESTORE/$collection" | jq '(.documents // []) | length'
}

echo "=== PR #282 Smoke Tests: POST /venues/suggest ==="
echo "API: $API"
echo "Firestore emulator: $FS_EMU"
echo "Auth emulator: $FIREBASE_AUTH_EMULATOR_HOST"
echo ""

require_cmd curl
require_cmd jq

HEALTH=$(curl -sS "$API/health" 2>/dev/null || true)
API_OK=$(echo "$HEALTH" | jq -r 'if .status == "ok" then "true" else "false" end' 2>/dev/null || echo false)
check "API health endpoint is reachable" "$API_OK"
if [ "$API_OK" != "true" ]; then
  echo "ABORT: API is not reachable. Start it with: make api-dev-emu-auth"
  exit 1
fi

FS_OK=$(curl -sS "$FIRESTORE" >/dev/null 2>&1 && echo true || echo false)
check "Firestore emulator REST API is reachable" "$FS_OK"
if [ "$FS_OK" != "true" ]; then
  echo "ABORT: Firestore emulator is not reachable. Start it with: make emu-all"
  exit 1
fi

TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null || true)
TOKEN_OK=$([ -n "$TOKEN" ] && echo true || echo false)
check "Auth emulator token acquired for user_ignatios" "$TOKEN_OK"
if [ "$TOKEN_OK" != "true" ]; then
  echo "ABORT: could not get auth token. Ensure the auth emulator is running."
  exit 1
fi

echo ""
echo "--- Happy path writes to venueSuggestions ---"
RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Local Club",
    "coordinates": {"lat": 37.95, "lng": 23.72},
    "sport": "padel",
    "notes": "2 outdoor courts, open until 11pm"
  }')
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')

check "valid request returns 201" "$([ "$HTTP_CODE" = "201" ] && echo true || echo false)"
SUGGESTION_ID=$(echo "$BODY" | jq -r '.suggestionId // empty' 2>/dev/null || true)
check "response contains suggestionId" "$([ -n "$SUGGESTION_ID" ] && echo true || echo false)"

if [ -n "$SUGGESTION_ID" ]; then
  DOC=$(curl -sS "$FIRESTORE/venueSuggestions/$SUGGESTION_ID")
  FS_NAME=$(echo "$DOC" | jq -r '.fields.name.stringValue // ""')
  FS_SPORT=$(echo "$DOC" | jq -r '.fields.sport.stringValue // ""')
  FS_SUGGESTED_BY=$(echo "$DOC" | jq -r '.fields.suggestedBy.stringValue // ""')
  FS_STATUS=$(echo "$DOC" | jq -r '.fields.status.stringValue // ""')
  FS_CREATED_AT=$(echo "$DOC" | jq -r '.fields.createdAt.timestampValue // ""')

  check "Firestore stores name" "$([ "$FS_NAME" = "My Local Club" ] && echo true || echo false)"
  check "Firestore stores sport" "$([ "$FS_SPORT" = "padel" ] && echo true || echo false)"
  check "Firestore stores suggestedBy from auth user" "$([ "$FS_SUGGESTED_BY" = "user_ignatios" ] && echo true || echo false)"
  check "Firestore stores pending status" "$([ "$FS_STATUS" = "pending" ] && echo true || echo false)"
  check "Firestore stores createdAt timestamp" "$([ -n "$FS_CREATED_AT" ] && echo true || echo false)"
fi

echo ""
echo "--- Optional notes ---"
RESPONSE_NO_NOTES=$(curl -sS -w "\n%{http_code}" -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Quiet Court","coordinates":{"lat":37.9,"lng":23.7},"sport":"tennis"}')
HTTP_NO_NOTES=$(echo "$RESPONSE_NO_NOTES" | tail -1)
BODY_NO_NOTES=$(echo "$RESPONSE_NO_NOTES" | sed '$d')
ID_NO_NOTES=$(echo "$BODY_NO_NOTES" | jq -r '.suggestionId // empty' 2>/dev/null || true)
check "notes can be omitted and request returns 201" "$([ "$HTTP_NO_NOTES" = "201" ] && echo true || echo false)"
check "notes-omitted response contains suggestionId" "$([ -n "$ID_NO_NOTES" ] && echo true || echo false)"

echo ""
echo "--- Validation and auth failures ---"
NO_AUTH=$(http_code -X POST "$API/venues/suggest" \
  -H "Content-Type: application/json" \
  -d '{"name":"X","coordinates":{"lat":1,"lng":1},"sport":"padel"}')
check "missing auth returns 401" "$([ "$NO_AUTH" = "401" ] && echo true || echo false)"

BAD_SPORT=$(http_code -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"X","coordinates":{"lat":1,"lng":1},"sport":"chess"}')
check "invalid sport returns 422" "$([ "$BAD_SPORT" = "422" ] && echo true || echo false)"

BAD_COORDS=$(http_code -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"X","coordinates":{"lat":100,"lng":1},"sport":"padel"}')
check "invalid coordinates return 422" "$([ "$BAD_COORDS" = "422" ] && echo true || echo false)"

MISSING_NAME=$(http_code -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"coordinates":{"lat":37.9,"lng":23.7},"sport":"padel"}')
check "missing name returns 422" "$([ "$MISSING_NAME" = "422" ] && echo true || echo false)"

BLANK_NAME=$(http_code -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"   ","coordinates":{"lat":37.9,"lng":23.7},"sport":"padel"}')
check "whitespace-only name returns 422" "$([ "$BLANK_NAME" = "422" ] && echo true || echo false)"

echo ""
echo "--- Trimmed names and live venues isolation ---"
RESPONSE_TRIMMED=$(curl -sS -w "\n%{http_code}" -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"  Trimmed Court  ","coordinates":{"lat":37.91,"lng":23.71},"sport":"padel"}')
HTTP_TRIMMED=$(echo "$RESPONSE_TRIMMED" | tail -1)
BODY_TRIMMED=$(echo "$RESPONSE_TRIMMED" | sed '$d')
ID_TRIMMED=$(echo "$BODY_TRIMMED" | jq -r '.suggestionId // empty' 2>/dev/null || true)
check "trimmed-name request returns 201" "$([ "$HTTP_TRIMMED" = "201" ] && echo true || echo false)"
if [ -n "$ID_TRIMMED" ]; then
  TRIMMED_DOC=$(curl -sS "$FIRESTORE/venueSuggestions/$ID_TRIMMED")
  TRIMMED_NAME=$(echo "$TRIMMED_DOC" | jq -r '.fields.name.stringValue // ""')
  check "leading/trailing name whitespace is trimmed before persistence" "$([ "$TRIMMED_NAME" = "Trimmed Court" ] && echo true || echo false)"
fi

VENUES_COUNT_BEFORE=$(document_count venues)
curl -sS -o /dev/null -X POST "$API/venues/suggest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Should Not Appear","coordinates":{"lat":37.9,"lng":23.7},"sport":"pickleball"}'
VENUES_COUNT_AFTER=$(document_count venues)
check "live venues collection count is unchanged" "$([ "$VENUES_COUNT_AFTER" = "$VENUES_COUNT_BEFORE" ] && echo true || echo false)"

echo ""
echo "==============================="
echo "  PASS: $PASS    FAIL: $FAIL"
echo "==============================="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
