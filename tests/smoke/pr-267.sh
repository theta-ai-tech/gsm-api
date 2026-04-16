#!/usr/bin/env bash
# Smoke test for PR #267 — VEN-4: Google Places autocomplete proxy endpoint
#
# Prerequisites:
#   Terminal 1: make emu-all
#   Terminal 2: make seed-emu && make api-dev-emu-auth
#
# The test exercises the endpoint with mocked/absent Google Places API key
# since we cannot call the real Google API in smoke tests. It validates
# request validation, auth, response shape, and 503 when the key is missing.
#
# Run from the gsm-api root: bash tests/smoke/pr-267.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PASS=0
FAIL=0

API_BASE="${API_BASE_URL:-http://localhost:8000}"
AUTH_EMU="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"

check() {
  local desc="$1" result="$2"
  if [ "$result" = "true" ]; then
    echo "  PASS: $desc"
    ((PASS++))
  else
    echo "  FAIL: $desc"
    ((FAIL++))
  fi
}

echo "=== PR #267 Smoke Tests: GET /venues/search ==="
echo ""

# --- Pre-flight: API reachable ---
echo "--- Pre-flight ---"
HEALTH=$(curl -sf "${API_BASE}/health" 2>/dev/null)
API_OK=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('status')=='ok' else 'false')" 2>/dev/null || echo false)
check "API reachable at ${API_BASE}" "$API_OK"

if [ "$API_OK" != "true" ]; then
  echo ""
  echo "ABORT: API not reachable. Start it with: make api-dev-emu-auth"
  exit 1
fi

# --- Get auth token ---
echo ""
echo "--- Auth setup ---"
TOKEN=$("$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios 2>/dev/null)
TOKEN_OK=$([ -n "$TOKEN" ] && echo true || echo false)
check "Got auth token for user_ignatios" "$TOKEN_OK"

if [ "$TOKEN_OK" != "true" ]; then
  echo ""
  echo "ABORT: Could not get auth token. Ensure auth emulator is running."
  exit 1
fi

# --- Test 1: No auth returns 401 ---
echo ""
echo "--- Auth tests ---"
RESP_401=$(curl -sf -o /dev/null -w "%{http_code}" "${API_BASE}/venues/search?q=padel" 2>/dev/null)
check "No auth token returns 401" "$([ "$RESP_401" = "401" ] && echo true || echo false)"

# --- Test 2: Missing q param returns 422 ---
echo ""
echo "--- Validation tests ---"
RESP_NO_Q=$(curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "${API_BASE}/venues/search" 2>/dev/null)
check "Missing q param returns 422" "$([ "$RESP_NO_Q" = "422" ] && echo true || echo false)"

# --- Test 3: Empty q param returns 422 ---
RESP_EMPTY_Q=$(curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "${API_BASE}/venues/search?q=" 2>/dev/null)
check "Empty q param returns 422" "$([ "$RESP_EMPTY_Q" = "422" ] && echo true || echo false)"

# --- Test 4: Invalid lat returns 422 ---
RESP_BAD_LAT=$(curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "${API_BASE}/venues/search?q=padel&lat=100" 2>/dev/null)
check "lat=100 returns 422" "$([ "$RESP_BAD_LAT" = "422" ] && echo true || echo false)"

# --- Test 5: Invalid lng returns 422 ---
RESP_BAD_LNG=$(curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "${API_BASE}/venues/search?q=padel&lat=37.9&lng=200" 2>/dev/null)
check "lng=200 returns 422" "$([ "$RESP_BAD_LNG" = "422" ] && echo true || echo false)"

# --- Test 6: Valid request returns 200 with results array ---
echo ""
echo "--- Endpoint response tests ---"
# Note: Without a real GOOGLE_PLACES_API_KEY, the endpoint may return 503 or
# return only curated results. We test both scenarios.
RESP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "${API_BASE}/venues/search?q=padel" 2>/dev/null)

if [ "$RESP_CODE" = "200" ]; then
  check "GET /venues/search?q=padel returns 200" "true"

  RESP_BODY=$(curl -sf -H "Authorization: Bearer $TOKEN" \
    "${API_BASE}/venues/search?q=padel" 2>/dev/null)

  # Check results array exists
  HAS_RESULTS=$(echo "$RESP_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('true' if isinstance(d.get('results'), list) else 'false')
" 2>/dev/null || echo false)
  check "Response has 'results' array" "$HAS_RESULTS"

  # Check max 5 results
  RESULTS_LTE_5=$(echo "$RESP_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('true' if len(d.get('results',[])) <= 5 else 'false')
" 2>/dev/null || echo false)
  check "Results count <= 5" "$RESULTS_LTE_5"

  # Check result shape (if any results)
  SHAPE_OK=$(echo "$RESP_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
results = d.get('results',[])
if not results:
    print('true')  # no results to check
    sys.exit()
r = results[0]
keys_ok = all(k in r for k in ('venueId','placeId','name','coordinates'))
coords = r.get('coordinates',{})
coords_ok = 'lat' in coords and 'lng' in coords
print('true' if keys_ok and coords_ok else 'false')
" 2>/dev/null || echo false)
  check "Result shape has venueId, placeId, name, coordinates.{lat,lng}" "$SHAPE_OK"

elif [ "$RESP_CODE" = "503" ]; then
  # No Google API key configured — this is expected in smoke test env
  check "GET /venues/search returns 503 (no API key configured)" "true"

  RESP_503_BODY=$(curl -sf -H "Authorization: Bearer $TOKEN" \
    "${API_BASE}/venues/search?q=padel" 2>/dev/null || true)
  HAS_DETAIL=$(echo "$RESP_503_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('true' if 'Google Places API key' in d.get('detail','') else 'false')
" 2>/dev/null || echo false)
  check "503 response mentions missing API key" "$HAS_DETAIL"
else
  check "GET /venues/search?q=padel returns 200 or 503" "false"
fi

# --- Test 7: Unit tests pass ---
echo ""
echo "--- Unit test verification ---"
cd "$REPO_ROOT"
UNIT_OUTPUT=$(. .venv/bin/activate && \
  GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0 \
  FIRESTORE_EMULATOR_HOST=127.0.0.1:8082 \
  pytest tests/unit/routers/test_venues_router.py tests/unit/services/test_places_service.py -q 2>&1)
UNIT_OK=$(echo "$UNIT_OUTPUT" | grep -q "passed" && echo true || echo false)
check "Unit tests for venues router and places service pass" "$UNIT_OK"

# --- Summary ---
echo ""
echo "==============================="
echo "  PASS: $PASS    FAIL: $FAIL"
echo "==============================="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
