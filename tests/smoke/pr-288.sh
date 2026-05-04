#!/usr/bin/env bash
# Smoke tests for PR #288: feat: DBL-7 update GET /me/state payloads for doubles (#171)
# Usage: bash tests/smoke/pr-288.sh
#
# Requires: make emu-all + API_BASE_URL pointing at the PR API.
#
# This script exercises the new doubles-aware fields on the GET /me/state
# payloads (match_type, partner_uid, partner_name, participants array). It is
# self-contained and idempotent: any broadcast/offer state for the test users
# is reset on entry and on exit so repeated runs converge.

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

cancel_broadcast_for() {
  local tok="$1"
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $tok" "$API/me/broadcast" || true
}

cleanup() {
  cancel_broadcast_for "$TOKEN_IG"
  cancel_broadcast_for "$TOKEN_AL"
  cancel_broadcast_for "$TOKEN_BO"
}
trap cleanup EXIT
cleanup

# ── Tests ───────────────────────────────────────────────────────────────────

# Test 1: Singles broadcast => match_type=singles, partner fields null.
echo "Test 1: BROADCAST_ACTIVE for a singles broadcast surfaces singles defaults"
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
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_IG" "$API/me/state")
assert_eq "mode is BROADCAST_ACTIVE" "$(echo "$RESP" | jq -r '.mode')" "BROADCAST_ACTIVE"
assert_eq "match_type defaults to singles" "$(echo "$RESP" | jq -r '.payload.match_type')" "singles"
assert_eq "partner_uid is null" "$(echo "$RESP" | jq -r '.payload.partner_uid')" "null"
assert_eq "partner_name is null" "$(echo "$RESP" | jq -r '.payload.partner_name')" "null"
cancel_broadcast_for "$TOKEN_IG"

# Test 2: Doubles broadcast => match_type=doubles, partner_uid/name populated.
echo "Test 2: BROADCAST_ACTIVE for a doubles broadcast carries partner_name"
curl -s -o /dev/null -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN_IG" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "padel",
    "match_type": "doubles",
    "broadcast_type": "find_opponent",
    "partner_uid": "user_alice",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 101}
  }'
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_IG" "$API/me/state")
assert_eq "match_type is doubles" "$(echo "$RESP" | jq -r '.payload.match_type')" "doubles"
assert_eq "partner_uid is user_alice" "$(echo "$RESP" | jq -r '.payload.partner_uid')" "user_alice"
PNAME=$(echo "$RESP" | jq -r '.payload.partner_name')
if [ -n "$PNAME" ] && [ "$PNAME" != "null" ]; then
  echo "  ✓ partner_name resolved (=\"$PNAME\")"
  ((PASS++)) || true
else
  echo "  ✗ partner_name resolved"
  echo "    expected: non-null name"
  echo "    actual:   $PNAME"
  ((FAIL++)) || true
fi
cancel_broadcast_for "$TOKEN_IG"

# Test 3: DISCOVERY user has empty payload.
echo "Test 3: DISCOVERY mode payload is empty"
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_BO" "$API/me/state")
assert_eq "mode is DISCOVERY" "$(echo "$RESP" | jq -r '.mode')" "DISCOVERY"
assert_eq "payload is empty object" "$(echo "$RESP" | jq -c '.payload')" "{}"

# Test 4: Singles outgoing offer => match_type=singles, partner fields null.
echo "Test 4: OUTGOING_OFFER_PENDING for a singles offer surfaces singles defaults"
# Alice broadcasts so Ignatios can challenge. Using Alice (not Bob) leaves Bob
# in DISCOVERY so the recipient flips to INCOMING_OFFER_PENDING in Test 5
# below — recipients who already have an active broadcast stay
# BROADCAST_ACTIVE while the offer queues in pendingIncomingOfferIds, which
# would not exercise the INCOMING_OFFER_PENDING payload we want to assert on.
curl -s -o /dev/null -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN_AL" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 101}
  }'
BCAST_ID=$(curl -s -H "Authorization: Bearer $TOKEN_AL" "$API/me/state" | jq -r '.payload.broadcast_id')
curl -s -o /dev/null -X POST "$API/me/offers" \
  -H "Authorization: Bearer $TOKEN_IG" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"user_alice\",
    \"sport\": \"tennis\",
    \"proposed_time\": \"2099-01-01T10:00:00Z\",
    \"source_broadcast_id\": \"$BCAST_ID\",
    \"message\": \"smoke test\"
  }"
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_IG" "$API/me/state")
assert_eq "outgoing mode" "$(echo "$RESP" | jq -r '.mode')" "OUTGOING_OFFER_PENDING"
assert_eq "outgoing match_type=singles" "$(echo "$RESP" | jq -r '.payload.match_type')" "singles"
assert_eq "outgoing partner_uid null" "$(echo "$RESP" | jq -r '.payload.partner_uid')" "null"
assert_eq "outgoing partner_name null" "$(echo "$RESP" | jq -r '.payload.partner_name')" "null"

# Test 5: Recipient sees the matching IncomingOfferPayload. Alice broadcast +
# offer queue → Alice stays BROADCAST_ACTIVE. To exercise the
# INCOMING_OFFER_PENDING branch, send a direct offer to Bob (DISCOVERY).
echo "Test 5: INCOMING_OFFER_PENDING surfaces match_type/partner fields"
# Cancel Ignatios's outgoing offer first so we can send a fresh one to Bob.
OFFER_ID=$(curl -s -H "Authorization: Bearer $TOKEN_IG" "$API/me/state" | jq -r '.payload.offer_id')
curl -s -o /dev/null -X POST -H "Authorization: Bearer $TOKEN_IG" \
  "$API/me/offers/$OFFER_ID/cancel"
curl -s -o /dev/null -X POST "$API/me/offers" \
  -H "Authorization: Bearer $TOKEN_IG" \
  -H "Content-Type: application/json" \
  -d '{
    "to_uid": "user_bob",
    "sport": "tennis",
    "proposed_time": "2099-01-01T10:00:00Z",
    "message": "smoke test direct"
  }'
RESP=$(curl -s -H "Authorization: Bearer $TOKEN_BO" "$API/me/state")
assert_eq "incoming mode" "$(echo "$RESP" | jq -r '.mode')" "INCOMING_OFFER_PENDING"
assert_eq "incoming match_type=singles" "$(echo "$RESP" | jq -r '.payload.match_type')" "singles"
assert_eq "incoming partner_uid null" "$(echo "$RESP" | jq -r '.payload.partner_uid')" "null"

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "─────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
echo "─────────────────────────────────────"

[ "$FAIL" -eq 0 ]
