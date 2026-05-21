#!/usr/bin/env bash
# Smoke tests for PR #307: feat: LG-11 add GET /leagues/{leagueId}/matches — upcoming + completed (#258)
# Generated: 2026-05-21
# Usage: bash tests/smoke/pr-307.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8307}"

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

assert_http() {
  local name="$1" actual="$2" expected="$3"
  assert_eq "$name" "$actual" "$expected"
}

# ── Token acquisition ────────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

BOB_TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_bob -t 2>/dev/null)
if [ -z "$BOB_TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_bob. Is the auth emulator running?"
  exit 1
fi

echo ""
echo "=== Smoke tests — PR #307: GET /leagues/{leagueId}/matches ==="
echo ""

# ── Test 1: Upcoming matches (default type) ──────────────────────────────────
echo "--- 1. Upcoming matches ---"
RESP=$(curl -s -o /tmp/pr307_resp1.json -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/matches")
assert_http "GET /leagues/padel-local-2025/matches returns 200" "$RESP" "200"

MATCHES_TYPE=$(jq 'type' /tmp/pr307_resp1.json 2>/dev/null || echo "null")
assert_eq "response is a JSON object" "$MATCHES_TYPE" '"object"'

HAS_MATCHES=$(jq 'has("matches")' /tmp/pr307_resp1.json 2>/dev/null || echo "false")
assert_eq "response has matches key" "$HAS_MATCHES" "true"

HAS_CURSOR=$(jq 'has("next_cursor")' /tmp/pr307_resp1.json 2>/dev/null || echo "false")
assert_eq "response has next_cursor key" "$HAS_CURSOR" "true"

MATCHES_IS_ARRAY=$(jq '.matches | type' /tmp/pr307_resp1.json 2>/dev/null || echo "null")
assert_eq "matches is an array" "$MATCHES_IS_ARRAY" '"array"'

# ── Test 2: Completed matches ────────────────────────────────────────────────
echo "--- 2. Completed matches ---"
RESP=$(curl -s -o /tmp/pr307_resp2.json -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/matches?type=completed")
assert_http "GET /leagues/padel-local-2025/matches?type=completed returns 200" "$RESP" "200"

COMPLETED_ARRAY=$(jq '.matches | type' /tmp/pr307_resp2.json 2>/dev/null || echo "null")
assert_eq "completed response has matches array" "$COMPLETED_ARRAY" '"array"'

# ── Test 3: Limit parameter ──────────────────────────────────────────────────
echo "--- 3. Limit parameter ---"
RESP=$(curl -s -o /tmp/pr307_resp3.json -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/matches?type=upcoming&limit=2")
assert_http "GET ...?type=upcoming&limit=2 returns 200" "$RESP" "200"

MATCH_COUNT=$(jq '.matches | length' /tmp/pr307_resp3.json 2>/dev/null || echo "-1")
assert_eq "limit=2 returns at most 2 matches" "$([ "$MATCH_COUNT" -le 2 ] && echo 'ok' || echo "got $MATCH_COUNT")" "ok"

# ── Test 4: 404 — league not found ──────────────────────────────────────────
echo "--- 4. 404 — league not found ---"
RESP=$(curl -s -o /tmp/pr307_resp4.json -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/nonexistent-league/matches")
assert_http "GET /leagues/nonexistent-league/matches returns 404" "$RESP" "404"

DETAIL=$(jq -r '.detail' /tmp/pr307_resp4.json 2>/dev/null || echo "null")
assert_eq "404 detail message" "$DETAIL" "League not found"

# ── Test 5: 403 — non-member ─────────────────────────────────────────────────
echo "--- 5. 403 — non-member (user_bob on tennis-local-2025) ---"
RESP=$(curl -s -o /tmp/pr307_resp5.json -w "%{http_code}" \
  -H "Authorization: Bearer $BOB_TOKEN" \
  "$API/leagues/tennis-local-2025/matches")
assert_http "GET /leagues/tennis-local-2025/matches as non-member returns 403" "$RESP" "403"

DETAIL=$(jq -r '.detail' /tmp/pr307_resp5.json 2>/dev/null || echo "null")
assert_eq "403 detail message" "$DETAIL" "You are not allowed to access this league"

# ── Test 6: 401 — no auth token ─────────────────────────────────────────────
echo "--- 6. 401 — no auth ---"
RESP=$(curl -s -o /tmp/pr307_resp6.json -w "%{http_code}" \
  "$API/leagues/padel-local-2025/matches")
assert_http "GET without auth returns 401" "$RESP" "401"

# ── Test 7: 422 — invalid type param ────────────────────────────────────────
echo "--- 7. 422 — invalid type ---"
RESP=$(curl -s -o /tmp/pr307_resp7.json -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/padel-local-2025/matches?type=invalid")
assert_http "GET ...?type=invalid returns 422" "$RESP" "422"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #307: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
