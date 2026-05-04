#!/usr/bin/env bash
# Smoke tests for PR #289: feat: DBL-8 discovery feed — broadcast_type badges and doubles filter (#172)
# Usage: bash tests/smoke/pr-289.sh
#
# Requires: make emu-all + API_BASE_URL pointing at the PR API.
#
# Tests the DISCOVERY feed payload: broadcast cards with match_type/broadcast_type
# badges, annotation counts, and the ?match_type doubles/singles filter.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-${API:-http://localhost:8000}}"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR (or $REPO_ROOT/.venv). Run 'make venv && make install' in the main checkout."
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# ── Helpers ────────────────────────────────────────────────────────────────

assert_eq() {
  local name="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    ((FAIL++)) || true
  fi
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (expected to contain: $needle)"
    ((FAIL++)) || true
  fi
}

assert_not_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  ✗ $name (should NOT contain: $needle)"
    ((FAIL++)) || true
  else
    echo "  ✓ $name"
    ((PASS++)) || true
  fi
}

get_token() {
  bash "$REPO_ROOT/scripts/get_emu_token.sh" "$1" -t 2>/dev/null
}

TOKEN_IG=$(get_token user_ignatios)
TOKEN_AL=$(get_token user_alice)
TOKEN_BO=$(get_token user_bob)
if [ -z "$TOKEN_IG" ] || [ -z "$TOKEN_AL" ] || [ -z "$TOKEN_BO" ]; then
  echo "ERROR: Could not get auth tokens. Is the auth emulator running and seeded?"
  exit 1
fi

FIRESTORE_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FS_URL="http://$FIRESTORE_HOST/v1/projects/$PROJECT/databases/(default)/documents"

cancel_broadcast_for() {
  local tok="$1"
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $tok" "$API/me/broadcast" || true
}

cleanup() {
  cancel_broadcast_for "$TOKEN_IG"
  cancel_broadcast_for "$TOKEN_AL"
  cancel_broadcast_for "$TOKEN_BO"
  # Remove any manually seeded broadcasts created by this script
  for bc_id in smoke_bc_singles smoke_bc_doubles smoke_bc_fourth; do
    curl -s -o /dev/null -X DELETE "$FS_URL/broadcasts/$bc_id" || true
  done
}
trap cleanup EXIT
cleanup

# ── Helper: seed a broadcast directly via Firestore REST (emulator) ─────────
seed_broadcast() {
  local doc_id="$1" owner_uid="$2" owner_name="$3" match_type="$4" broadcast_type="$5"
  curl -s -o /dev/null -X PATCH \
    "$FS_URL/broadcasts/$doc_id" \
    -H "Content-Type: application/json" \
    -d "{
      \"fields\": {
        \"ownerUid\": {\"stringValue\": \"$owner_uid\"},
        \"ownerName\": {\"stringValue\": \"$owner_name\"},
        \"sport\": {\"stringValue\": \"tennis\"},
        \"matchType\": {\"stringValue\": \"$match_type\"},
        \"broadcastType\": {\"stringValue\": \"$broadcast_type\"},
        \"partnerUid\": {\"nullValue\": null},
        \"availability\": {\"stringValue\": \"today\"},
        \"courtStatus\": {\"stringValue\": \"need_court\"},
        \"courtLocation\": {\"nullValue\": null},
        \"venueRef\": {\"nullValue\": null},
        \"status\": {\"stringValue\": \"active\"},
        \"expiresAt\": {\"timestampValue\": \"2099-01-01T00:00:00Z\"},
        \"createdAt\": {\"timestampValue\": \"2026-05-04T12:00:00Z\"},
        \"location\": {\"mapValue\": {\"fields\": {}}}
      }
    }"
}

# ── Tests ────────────────────────────────────────────────────────────────────

echo ""
echo "=== Test 1: DISCOVERY mode returns typed payload (not empty object) ==="
# Ignatios, Alice, Bob are all in DISCOVERY by default after seed
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_BO" "$API/me/state")
assert_eq "mode is DISCOVERY" "$(echo "$RESP" | jq -r '.mode')" "DISCOVERY"
assert_eq "payload has broadcasts key" \
  "$(echo "$RESP" | jq 'has("payload") and (.payload | type) == "object" and (.payload | has("broadcasts"))')" "true"
assert_eq "broadcasts is an array" \
  "$(echo "$RESP" | jq '.payload.broadcasts | type')" '"array"'

echo ""
echo "=== Test 2: Annotations present with correct keys ==="
assert_eq "annotations has nearby_count" \
  "$(echo "$RESP" | jq '.annotations | has("nearby_count")')" "true"
assert_eq "annotations has doubles_count" \
  "$(echo "$RESP" | jq '.annotations | has("doubles_count")')" "true"
assert_eq "annotations has find_fourth_count" \
  "$(echo "$RESP" | jq '.annotations | has("find_fourth_count")')" "true"

echo ""
echo "=== Test 3: Broadcast cards carry match_type and broadcast_type badges ==="
# Seed 3 broadcasts for 3 different virtual users
seed_broadcast "smoke_bc_singles"   "virt_singles"  "Virt Singles"  "singles" "find_opponent"
seed_broadcast "smoke_bc_doubles"   "virt_doubles"  "Virt Doubles"  "doubles" "find_opponent"
seed_broadcast "smoke_bc_fourth"    "virt_fourth"   "Virt Fourth"   "doubles" "find_fourth"

RESP=$(curl -s -H "Authorization: Bearer $TOKEN_BO" "$API/me/state")
BROADCASTS=$(echo "$RESP" | jq -c '.payload.broadcasts')

# Check singles card
SINGLES=$(echo "$BROADCASTS" | jq -c '.[] | select(.broadcast_id == "smoke_bc_singles")')
assert_eq "singles card: match_type=singles" \
  "$(echo "$SINGLES" | jq -r '.match_type')" "singles"
assert_eq "singles card: broadcast_type=find_opponent" \
  "$(echo "$SINGLES" | jq -r '.broadcast_type')" "find_opponent"

# Check doubles card
DOUBLES=$(echo "$BROADCASTS" | jq -c '.[] | select(.broadcast_id == "smoke_bc_doubles")')
assert_eq "doubles card: match_type=doubles" \
  "$(echo "$DOUBLES" | jq -r '.match_type')" "doubles"
assert_eq "doubles card: broadcast_type=find_opponent" \
  "$(echo "$DOUBLES" | jq -r '.broadcast_type')" "find_opponent"

# Check find_fourth card
FOURTH=$(echo "$BROADCASTS" | jq -c '.[] | select(.broadcast_id == "smoke_bc_fourth")')
assert_eq "find_fourth card: match_type=doubles" \
  "$(echo "$FOURTH" | jq -r '.match_type')" "doubles"
assert_eq "find_fourth card: broadcast_type=find_fourth" \
  "$(echo "$FOURTH" | jq -r '.broadcast_type')" "find_fourth"

echo ""
echo "=== Test 4: Annotation counts ==="
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_BO" "$API/me/state")
NEARBY=$(echo "$RESP" | jq '.annotations.nearby_count')
DOUBLES=$(echo "$RESP" | jq '.annotations.doubles_count')
FOURTH=$(echo "$RESP" | jq '.annotations.find_fourth_count')
TOTAL=$(echo "$RESP" | jq '.payload.broadcasts | length')

assert_eq "nearby_count equals card count" "$NEARBY" "$TOTAL"
# At least 2 doubles (smoke_bc_doubles + smoke_bc_fourth)
if [ "$DOUBLES" -ge 2 ]; then
  echo "  ✓ doubles_count >= 2 (actual=$DOUBLES)"
  ((PASS++)) || true
else
  echo "  ✗ doubles_count should be >= 2, got $DOUBLES"
  ((FAIL++)) || true
fi
# At least 1 find_fourth
if [ "$FOURTH" -ge 1 ]; then
  echo "  ✓ find_fourth_count >= 1 (actual=$FOURTH)"
  ((PASS++)) || true
else
  echo "  ✗ find_fourth_count should be >= 1, got $FOURTH"
  ((FAIL++)) || true
fi

echo ""
echo "=== Test 5: ?match_type=doubles returns only doubles broadcasts ==="
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_BO" "$API/me/state?match_type=doubles")
assert_eq "mode still DISCOVERY" "$(echo "$RESP" | jq -r '.mode')" "DISCOVERY"
# All returned cards must have match_type=doubles
NON_DOUBLES=$(echo "$RESP" | jq '[.payload.broadcasts[] | select(.match_type != "doubles")] | length')
assert_eq "no non-doubles cards in doubles filter" "$NON_DOUBLES" "0"
assert_contains "smoke_bc_doubles present" \
  "$(echo "$RESP" | jq -c '[.payload.broadcasts[].broadcast_id]')" "smoke_bc_doubles"
assert_not_contains "smoke_bc_singles absent" \
  "$(echo "$RESP" | jq -c '[.payload.broadcasts[].broadcast_id]')" "smoke_bc_singles"

echo ""
echo "=== Test 6: ?match_type=singles returns only singles broadcasts ==="
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_BO" "$API/me/state?match_type=singles")
NON_SINGLES=$(echo "$RESP" | jq '[.payload.broadcasts[] | select(.match_type != "singles")] | length')
assert_eq "no non-singles cards in singles filter" "$NON_SINGLES" "0"
assert_contains "smoke_bc_singles present" \
  "$(echo "$RESP" | jq -c '[.payload.broadcasts[].broadcast_id]')" "smoke_bc_singles"
assert_not_contains "smoke_bc_doubles absent" \
  "$(echo "$RESP" | jq -c '[.payload.broadcasts[].broadcast_id]')" "smoke_bc_doubles"

echo ""
echo "=== Test 7: ?match_type=invalid returns 422 ==="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN_BO" "$API/me/state?match_type=invalid")
assert_eq "422 for invalid match_type" "$STATUS" "422"

echo ""
echo "=== Test 8: Caller's own broadcast excluded from feed ==="
curl -s -o /dev/null -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN_IG" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 101}
  }'
OWN_BCAST_ID=$(curl -s -H "Authorization: Bearer $TOKEN_IG" "$API/me/state" | jq -r '.payload.broadcast_id')
# Cancel own broadcast and go back to DISCOVERY via another endpoint
# Actually: Ignatios is now in BROADCAST_ACTIVE — but we can check from Bob's view
# Bob should not see Ignatios's broadcast if Ignatios is the viewer (can't test directly here)
# Instead: cancel Ignatios broadcast, then Ignatios sees Alice/Bob broadcasts but not own
cancel_broadcast_for "$TOKEN_IG"
# Now seed a broadcast as Ignatios via emulator REST to test exclusion
curl -s -o /dev/null -X PATCH \
  "$FS_URL/broadcasts/smoke_ig_own" \
  -H "Content-Type: application/json" \
  -d "{
    \"fields\": {
      \"ownerUid\": {\"stringValue\": \"user_ignatios\"},
      \"ownerName\": {\"stringValue\": \"Ignatios\"},
      \"sport\": {\"stringValue\": \"tennis\"},
      \"matchType\": {\"stringValue\": \"singles\"},
      \"broadcastType\": {\"stringValue\": \"find_opponent\"},
      \"partnerUid\": {\"nullValue\": null},
      \"availability\": {\"stringValue\": \"today\"},
      \"courtStatus\": {\"stringValue\": \"need_court\"},
      \"courtLocation\": {\"nullValue\": null},
      \"venueRef\": {\"nullValue\": null},
      \"status\": {\"stringValue\": \"active\"},
      \"expiresAt\": {\"timestampValue\": \"2099-01-01T00:00:00Z\"},
      \"createdAt\": {\"timestampValue\": \"2026-05-04T11:00:00Z\"},
      \"location\": {\"mapValue\": {\"fields\": {}}}
    }
  }"
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_IG" "$API/me/state")
assert_not_contains "own broadcast excluded" \
  "$(echo "$RESP" | jq -c '[.payload.broadcasts[].broadcast_id]')" "smoke_ig_own"
# Cleanup extra broadcast
curl -s -o /dev/null -X DELETE "$FS_URL/broadcasts/smoke_ig_own" || true

echo ""
echo "=== Test 9: Unauthenticated request returns 401 ==="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/me/state")
assert_eq "401 without token" "$STATUS" "401"

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "─────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
echo "─────────────────────────────────────"

[ "$FAIL" -eq 0 ]
