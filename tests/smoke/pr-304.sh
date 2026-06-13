#!/usr/bin/env bash
# Smoke tests for PR #304: feat: LG-9 add GET /leagues/{leagueId}/standings endpoint (#256)
# Generated: 2026-05-20
# Usage: bash tests/smoke/pr-304.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8304}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {sub(/^worktree /, ""); print; exit}')
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

# ── Token acquisition ────────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Setup: seed a member doc for user_ignatios in padel-local-2025 ───────────
# The seed_firestore.py does not seed league members, so we add one here to
# exercise standings with a non-empty result in a later test.
echo "Setting up: seeding league member user_ignatios in padel-local-2025..."
curl -s -X PATCH \
  "$FIRESTORE/leagues/padel-local-2025/members/user_ignatios" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "role": {"stringValue": "player"},
      "status": {"stringValue": "active"},
      "joinedAt": {"timestampValue": "2026-01-01T00:00:00Z"},
      "stats": {"mapValue": {"fields": {"wins": {"integerValue": "3"}, "losses": {"integerValue": "1"}}}}
    }
  }' > /dev/null

# ── Tests ────────────────────────────────────────────────────────────────────

echo ""
echo "Running smoke tests for PR #304..."
echo ""

# Test 1: 200 — authenticated owner/member gets standings
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/standings" | jq -r '.league_id // "null"')
assert_eq "GET /leagues/padel-local-2025/standings returns 200 with correct league_id" \
  "$ACTUAL" "padel-local-2025"

# Test 2: standings array is present and non-empty (seeded member above)
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/standings" | jq -r '.standings | length > 0')
assert_eq "standings array is non-empty after member seed" "$ACTUAL" "true"

# Test 3: StandingsEntry shape — rank field present
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/standings" \
  | jq -r '.standings[0].rank // "null"')
assert_eq "standings entry has rank field" "$ACTUAL" "1"

# Test 4: StandingsEntry shape — wins field matches seeded stats
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/standings" \
  | jq -r '.standings[0].wins // "null"')
assert_eq "standings entry wins=3 matches seeded stats" "$ACTUAL" "3"

# Test 5: 404 — non-existent league
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/does_not_exist/standings" | jq -r '.detail // "null"')
assert_eq "GET /leagues/does_not_exist/standings returns 404" \
  "$ACTUAL" "League not found"

# Test 6: HTTP status 404
ACTUAL=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/does_not_exist/standings")
assert_eq "404 status code for non-existent league" "$ACTUAL" "404"

# Test 7: 401 — no auth token
ACTUAL=$(curl -s -o /dev/null -w "%{http_code}" \
  "$API/leagues/padel-local-2025/standings")
assert_eq "GET /leagues/padel-local-2025/standings without token returns 401" \
  "$ACTUAL" "401"

# ── Teardown ─────────────────────────────────────────────────────────────────
echo ""
echo "Teardown: removing seeded member doc..."
curl -s -X DELETE \
  "$FIRESTORE/leagues/padel-local-2025/members/user_ignatios" > /dev/null

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #304: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
