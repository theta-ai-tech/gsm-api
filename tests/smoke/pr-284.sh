#!/usr/bin/env bash
# Smoke tests for PR #284: feat: DBL-3 extend broadcast model for doubles (#167)
# Generated: 2026-04-27
# Usage: bash tests/smoke/pr-284.sh
#
# Requires: make emu-all + make api-dev-emu-auth running
#
# This script exercises the new doubles fields on POST /me/broadcast and the
# BROADCAST_ACTIVE payload shape. It is self-contained and idempotent: it
# always cancels any active broadcast on the test user before each scenario
# and on exit, so repeated runs converge.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="http://localhost:8000"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

cancel_broadcast() {
  # Best-effort cancel; ignore if no active broadcast
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $TOKEN" "$API/me/broadcast" || true
}
trap cancel_broadcast EXIT

# Always start clean
cancel_broadcast

# ── Tests ───────────────────────────────────────────────────────────────────

# Test 1: Singles default broadcast still works (backwards compatibility)
echo "Test 1: POST /me/broadcast with singles defaults returns 201 + correct fields"
RESP=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
assert_eq "match_type defaults to singles" "$(echo "$RESP" | jq -r '.match_type')" "singles"
assert_eq "broadcast_type defaults to find_opponent" "$(echo "$RESP" | jq -r '.broadcast_type')" "find_opponent"
assert_eq "partner_uid defaults to null" "$(echo "$RESP" | jq -r '.partner_uid')" "null"

echo "Test 2: GET /me/state surfaces the singles defaults in BROADCAST_ACTIVE payload"
STATE=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/me/state")
assert_eq "mode is BROADCAST_ACTIVE" "$(echo "$STATE" | jq -r '.mode')" "BROADCAST_ACTIVE"
assert_eq "payload.match_type=singles" "$(echo "$STATE" | jq -r '.payload.match_type')" "singles"
assert_eq "payload.broadcast_type=find_opponent" "$(echo "$STATE" | jq -r '.payload.broadcast_type')" "find_opponent"
assert_eq "payload.partner_uid is null" "$(echo "$STATE" | jq -r '.payload.partner_uid')" "null"

cancel_broadcast

# Test 3: Doubles + find_opponent without partner_uid → 422
echo "Test 3: doubles + find_opponent without partner_uid is rejected (422)"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "padel",
    "match_type": "doubles",
    "broadcast_type": "find_opponent",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
assert_eq "doubles+find_opponent without partner returns 422" "$HTTP_STATUS" "422"

# Test 4: Singles + find_fourth → 422
echo "Test 4: singles + find_fourth is rejected (422)"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "match_type": "singles",
    "broadcast_type": "find_fourth",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
assert_eq "singles+find_fourth returns 422" "$HTTP_STATUS" "422"

# Test 5: Doubles + find_opponent + partner_uid → 201
echo "Test 5: doubles + find_opponent + partner_uid creates a broadcast (201)"
RESP=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "padel",
    "match_type": "doubles",
    "broadcast_type": "find_opponent",
    "partner_uid": "user_alice",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
assert_eq "match_type=doubles" "$(echo "$RESP" | jq -r '.match_type')" "doubles"
assert_eq "broadcast_type=find_opponent" "$(echo "$RESP" | jq -r '.broadcast_type')" "find_opponent"
assert_eq "partner_uid=user_alice" "$(echo "$RESP" | jq -r '.partner_uid')" "user_alice"

BROADCAST_ID=$(echo "$RESP" | jq -r '.broadcast_id')

echo "Test 6: Firestore broadcast doc carries matchType / broadcastType / partnerUid"
DOC=$(curl -s "$FIRESTORE/broadcasts/$BROADCAST_ID")
assert_eq "doc.matchType=doubles" "$(echo "$DOC" | jq -r '.fields.matchType.stringValue')" "doubles"
assert_eq "doc.broadcastType=find_opponent" "$(echo "$DOC" | jq -r '.fields.broadcastType.stringValue')" "find_opponent"
assert_eq "doc.partnerUid=user_alice" "$(echo "$DOC" | jq -r '.fields.partnerUid.stringValue')" "user_alice"

echo "Test 7: GET /me/state surfaces the doubles fields in BROADCAST_ACTIVE payload"
STATE=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/me/state")
assert_eq "payload.match_type=doubles" "$(echo "$STATE" | jq -r '.payload.match_type')" "doubles"
assert_eq "payload.broadcast_type=find_opponent" "$(echo "$STATE" | jq -r '.payload.broadcast_type')" "find_opponent"
assert_eq "payload.partner_uid=user_alice" "$(echo "$STATE" | jq -r '.payload.partner_uid')" "user_alice"

cancel_broadcast

# Test 8: Doubles + find_fourth without partner → 201
echo "Test 8: doubles + find_fourth without partner_uid creates a broadcast (201)"
RESP=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "padel",
    "match_type": "doubles",
    "broadcast_type": "find_fourth",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
assert_eq "match_type=doubles" "$(echo "$RESP" | jq -r '.match_type')" "doubles"
assert_eq "broadcast_type=find_fourth" "$(echo "$RESP" | jq -r '.broadcast_type')" "find_fourth"
assert_eq "partner_uid is null" "$(echo "$RESP" | jq -r '.partner_uid')" "null"

cancel_broadcast

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #284: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
