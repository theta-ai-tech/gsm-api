#!/usr/bin/env bash
# Smoke tests for PR #301: feat: LG-8 add GET /leagues/{leagueId} league detail endpoint (#255)
# Generated: 2026-05-21
# Usage: bash tests/smoke/pr-301.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8301}"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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
  local name="$1" actual="$2" expected="$3"
  if echo "$actual" | grep -q "$expected"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected to contain: $expected"
    echo "    actual: $actual"
    ((FAIL++)) || true
  fi
}

# ── Token acquisition ────────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

echo ""
echo "── GET /leagues/{league_id} smoke tests (PR #301) ─────────────────────────"
echo ""

# ── Test 1: Fetch existing league returns 200 ────────────────────────────────
ACTUAL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025")
assert_eq "GET /leagues/padel-local-2025 returns 200" "$ACTUAL_STATUS" "200"

# ── Test 2: Response includes league_id ─────────────────────────────────────
ACTUAL_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025" | jq -r '.league_id // "null"')
assert_eq "league_id is padel-local-2025" "$ACTUAL_ID" "padel-local-2025"

# ── Test 3: Response includes full League fields (not just browse card) ───────
ACTUAL_FIELDS=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025" | jq -r 'keys | sort | join(",")')
assert_contains "response includes owner_uid field" "$ACTUAL_FIELDS" "owner_uid"
assert_contains "response includes season field" "$ACTUAL_FIELDS" "season"

# ── Test 4: Fetch non-existent league returns 404 ───────────────────────────
ACTUAL_404=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/does-not-exist")
assert_eq "GET /leagues/does-not-exist returns 404" "$ACTUAL_404" "404"

# ── Test 5: 404 detail message ───────────────────────────────────────────────
ACTUAL_DETAIL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/does-not-exist" | jq -r '.detail // "null"')
assert_eq "404 detail is 'League not found'" "$ACTUAL_DETAIL" "League not found"

# ── Test 6: No auth returns 401 ──────────────────────────────────────────────
ACTUAL_401=$(curl -s -o /dev/null -w "%{http_code}" \
  "$API/leagues/padel-local-2025")
assert_eq "GET /leagues/{id} without auth returns 401" "$ACTUAL_401" "401"

# ── Teardown ─────────────────────────────────────────────────────────────────
# No Firestore mutations — no teardown needed. Tests are read-only.

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #301: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
