#!/usr/bin/env bash
# Smoke tests for PR #332: feat: ONB-1 add POST /me onboarding endpoint (#321)
# Generated: 2026-06-01
# Usage: bash tests/smoke/pr-332.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8332}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# Fresh uid — not in seed data, so POST /me creates it from scratch
TEST_UID="user_smoke_332"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# ── Helpers ─────────────────────────────────────────────────────────────────

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
  local name="$1" actual="$2" substr="$3"
  if echo "$actual" | grep -q "$substr"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected to contain: $substr"
    echo "    actual: $actual"
    ((FAIL++)) || true
  fi
}

# ── Token acquisition ────────────────────────────────────────────────────────
# Use a fresh uid not present in seed data so POST /me can create the profile.
echo "Acquiring token for $TEST_UID ..."
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" "$TEST_UID" "${TEST_UID}@example.com" "test_pass_123" -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for $TEST_UID. Is the auth emulator running?"
  exit 1
fi
echo "  Token acquired."
echo ""

# ── Teardown: delete test user doc if it exists from a prior run ─────────────
curl -s -X DELETE "$FIRESTORE/users/$TEST_UID" > /dev/null 2>&1 || true

# ── Tests ────────────────────────────────────────────────────────────────────

echo "=== Step 1: POST /me creates a new user profile (201) ==="
CREATE_RESP=$(curl -s -o /tmp/pr332_create.json -w "%{http_code}" \
  -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Smoke Tester",
    "sports": ["padel"],
    "levels": {"padel": "intermediate"},
    "area": 1
  }')
assert_eq "POST /me returns 201" "$CREATE_RESP" "201"

CREATED_UID=$(jq -r '.uid // "null"' /tmp/pr332_create.json)
assert_eq "Response uid matches token uid" "$CREATED_UID" "$TEST_UID"

CREATED_NAME=$(jq -r '.name // "null"' /tmp/pr332_create.json)
assert_eq "Response name is correct" "$CREATED_NAME" "Smoke Tester"

CREATED_EMAIL=$(jq -r '.email // "null"' /tmp/pr332_create.json)
assert_eq "Response has an email" "$CREATED_EMAIL" "${TEST_UID}@example.com"

echo ""
echo "=== Step 2: Rankings at tier floor for intermediate level ==="
REG_TIER=$(jq -r '.rankings.padel.registration_tier // "null"' /tmp/pr332_create.json)
assert_eq "registrationTier = intermediate" "$REG_TIER" "intermediate"

PADEL_PTS=$(jq -r '.rankings.padel.pts // "null"' /tmp/pr332_create.json)
assert_eq "Initial pts = 2000 (intermediate floor)" "$PADEL_PTS" "2000"

echo ""
echo "=== Step 3: GET /users/{uid} returns the created profile ==="
GET_RESP=$(curl -s -o /tmp/pr332_get.json -w "%{http_code}" \
  "$API/users/$TEST_UID" \
  -H "Authorization: Bearer $TOKEN")
assert_eq "GET /users/{uid} returns 200" "$GET_RESP" "200"

GET_UID=$(jq -r '.uid // "null"' /tmp/pr332_get.json)
assert_eq "GET profile uid matches" "$GET_UID" "$TEST_UID"

echo ""
echo "=== Step 4: GET /me/state returns DISCOVERY mode ==="
STATE_RESP=$(curl -s -o /tmp/pr332_state.json -w "%{http_code}" \
  "$API/me/state?match_type=singles" \
  -H "Authorization: Bearer $TOKEN")
assert_eq "GET /me/state returns 200" "$STATE_RESP" "200"

STATE_MODE=$(jq -r '.mode // "null"' /tmp/pr332_state.json)
assert_eq "Mode is DISCOVERY" "$STATE_MODE" "DISCOVERY"

echo ""
echo "=== Step 5: Re-POST /me returns 409 (duplicate) ==="
DUPE_RESP=$(curl -s -o /tmp/pr332_dupe.json -w "%{http_code}" \
  -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Smoke Tester",
    "sports": ["padel"],
    "levels": {"padel": "intermediate"},
    "area": 1
  }')
assert_eq "Re-POST returns 409" "$DUPE_RESP" "409"
DUPE_DETAIL=$(jq -r '.detail // "null"' /tmp/pr332_dupe.json)
assert_contains "409 detail mentions 'already exists'" "$DUPE_DETAIL" "already exists"

echo ""
echo "=== Step 6: POST /me with missing level for declared sport returns 422 ==="
MISSING_LEVEL_RESP=$(curl -s -o /tmp/pr332_missing.json -w "%{http_code}" \
  -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Bad Request",
    "sports": ["padel", "tennis"],
    "levels": {"padel": "intermediate"},
    "area": 1
  }')
assert_eq "Missing level for sport returns 422" "$MISSING_LEVEL_RESP" "422"

# ── Teardown ─────────────────────────────────────────────────────────────────
echo ""
echo "Cleaning up: deleting test user doc ..."
curl -s -X DELETE "$FIRESTORE/users/$TEST_UID" > /dev/null 2>&1 || true
echo "  Done."

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #332: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
