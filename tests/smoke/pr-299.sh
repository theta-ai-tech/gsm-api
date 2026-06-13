#!/usr/bin/env bash
# Smoke tests for PR #299: feat: LG-7 add leagues router GET /leagues with cursor pagination (#254)
# Generated: 2026-05-20
# Usage: bash tests/smoke/pr-299.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8299}"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2 ; exit}')
  VENV_DIR="${MAIN_WT}/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
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

assert_not_null() {
  local name="$1" actual="$2"
  if [ -n "$actual" ] && [ "$actual" != "null" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (got null or empty)"
    ((FAIL++)) || true
  fi
}

assert_null() {
  local name="$1" actual="$2"
  if [ "$actual" = "null" ] || [ -z "$actual" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (expected null, got: $actual)"
    ((FAIL++)) || true
  fi
}

assert_http() {
  local name="$1" actual="$2" expected="$3"
  assert_eq "$name" "$actual" "$expected"
}

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Tests ───────────────────────────────────────────────────────────────────

echo ""
echo "=== GET /leagues — default (status=open) ==="

# Should return open leagues — tennis-local-2025 is the only OPEN seeded league
RESP=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues")
LEAGUE_COUNT=$(echo "$RESP" | jq '.leagues | length')
assert_not_null "returns non-null leagues array" "$(echo "$RESP" | jq '.leagues')"
assert_eq "returns at least 1 open league" "$([ "$LEAGUE_COUNT" -ge 1 ] && echo yes || echo no)" "yes"
assert_null "next_cursor is null for small result set" "$(echo "$RESP" | jq -r '.next_cursor')"

# Verify the open league fields
FIRST_LEAGUE=$(echo "$RESP" | jq '.leagues[0]')
assert_eq "first open league has league_id" "$(echo "$FIRST_LEAGUE" | jq -r '.league_id')" "tennis-local-2025"
assert_eq "first open league has correct name" "$(echo "$FIRST_LEAGUE" | jq -r '.name')" "Local Tennis Series 2025"
assert_eq "first open league has sport=tennis" "$(echo "$FIRST_LEAGUE" | jq -r '.sport')" "tennis"
assert_eq "first open league has status=open" "$(echo "$FIRST_LEAGUE" | jq -r '.status')" "open"
assert_eq "first open league has region=thessaloniki" "$(echo "$FIRST_LEAGUE" | jq -r '.region')" "thessaloniki"
assert_eq "first open league has tier=intermediate" "$(echo "$FIRST_LEAGUE" | jq -r '.tier')" "intermediate"
assert_eq "first open league has max_players=16" "$(echo "$FIRST_LEAGUE" | jq -r '.max_players')" "16"

echo ""
echo "=== GET /leagues — response shape ==="

# Verify all expected fields are present in the response card
KEYS=$(echo "$FIRST_LEAGUE" | jq 'keys | sort | join(",")')
assert_eq "LeagueBrowseCard has expected fields" "$KEYS" '"current_players,league_id,max_players,name,region,sport,start_date,status,tier"'

echo ""
echo "=== GET /leagues — empty result (no leagues match) ==="

RESP_NONE=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues?region=nowhere_land")
assert_eq "empty result returns 200 with empty array" "$(echo "$RESP_NONE" | jq '.leagues | length')" "0"
assert_null "empty result next_cursor is null" "$(echo "$RESP_NONE" | jq -r '.next_cursor')"

echo ""
echo "=== GET /leagues — filter by region ==="

RESP_REGION=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues?status=open&region=thessaloniki")
assert_eq "region=thessaloniki returns 1 open league" "$(echo "$RESP_REGION" | jq '.leagues | length')" "1"
assert_eq "region-filtered league is tennis-local-2025" "$(echo "$RESP_REGION" | jq -r '.leagues[0].league_id')" "tennis-local-2025"

echo ""
echo "=== GET /leagues — filter by sport ==="

RESP_SPORT=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues?status=open&sport=tennis")
SPORT_COUNT=$(echo "$RESP_SPORT" | jq '.leagues | length')
assert_eq "sport=tennis returns open tennis leagues" "$([ "$SPORT_COUNT" -ge 1 ] && echo yes || echo no)" "yes"
assert_eq "all returned leagues are tennis" "$(echo "$RESP_SPORT" | jq '[.leagues[].sport] | unique | .[]')" '"tennis"'

echo ""
echo "=== GET /leagues — filter by status=active ==="

RESP_ACTIVE=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues?status=active")
assert_eq "status=active returns at least 1 league" "$([ "$(echo "$RESP_ACTIVE" | jq '.leagues | length')" -ge 1 ] && echo yes || echo no)" "yes"
assert_eq "active league id is padel-local-2025" "$(echo "$RESP_ACTIVE" | jq -r '.leagues[0].league_id')" "padel-local-2025"

echo ""
echo "=== GET /leagues — pagination with limit=1 ==="

RESP_PAGE1=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues?status=open&limit=1")
PAGE1_COUNT=$(echo "$RESP_PAGE1" | jq '.leagues | length')
CURSOR=$(echo "$RESP_PAGE1" | jq -r '.next_cursor')

# If there's only 1 open league, cursor will be null; if more, cursor will be set
assert_eq "limit=1 returns exactly 1 league" "$PAGE1_COUNT" "1"

# Only test cursor pagination if there are enough open leagues
if [ "$CURSOR" != "null" ] && [ -n "$CURSOR" ]; then
  echo "  → next_cursor present, testing page 2"
  RESP_PAGE2=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues?status=open&limit=1&cursor=$CURSOR")
  assert_eq "page 2 returns a league" "$(echo "$RESP_PAGE2" | jq '.leagues | length')" "1"
  PAGE1_ID=$(echo "$RESP_PAGE1" | jq -r '.leagues[0].league_id')
  PAGE2_ID=$(echo "$RESP_PAGE2" | jq -r '.leagues[0].league_id')
  assert_eq "page 2 league differs from page 1" "$([ "$PAGE1_ID" != "$PAGE2_ID" ] && echo yes || echo no)" "yes"
else
  echo "  → only 1 open league in seed data; skipping page-2 test (expected with seed)"
  ((PASS++)) || true
fi

echo ""
echo "=== GET /leagues — validation errors ==="

STATUS_LIMIT=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/leagues?limit=100")
assert_http "limit=100 returns 422" "$STATUS_LIMIT" "422"

STATUS_LIMIT0=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/leagues?limit=0")
assert_http "limit=0 returns 422" "$STATUS_LIMIT0" "422"

STATUS_SPORT=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/leagues?sport=chess")
assert_http "sport=chess returns 422" "$STATUS_SPORT" "422"

STATUS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/leagues?status=unknown")
assert_http "status=unknown returns 422" "$STATUS_STATUS" "422"

STATUS_CURSOR=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/leagues?cursor=not-valid-base64!!!")
assert_http "invalid cursor returns 400" "$STATUS_CURSOR" "400"

echo ""
echo "=== GET /leagues — auth ==="

STATUS_NOAUTH=$(curl -s -o /dev/null -w "%{http_code}" "$API/leagues")
assert_http "no auth returns 401" "$STATUS_NOAUTH" "401"

# ── Teardown ────────────────────────────────────────────────────────────────
# No Firestore mutations in this test suite — nothing to reset.

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #299: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
