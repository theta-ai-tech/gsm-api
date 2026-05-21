#!/usr/bin/env bash
# Smoke test for PR #302 — LG-12: Migrate league member placeholder endpoints
# Usage: bash tests/smoke/pr-302.sh
# Prerequisites:
#   Terminal 1: make emu-all
#   Terminal 2: make seed-emu && make api-dev-emu-auth
set -euo pipefail

API="${API_BASE_URL:-http://localhost:8000}"
SCRIPTS_DIR="$(cd "$(dirname "$0")/../../scripts" && pwd)"

echo "=== PR #302 Smoke Tests: League member endpoints ==="

# Get a token for user_ignatios (not an admin of any league in seed data)
TOKEN=$("$SCRIPTS_DIR/get_emu_token.sh" user_ignatios -t)

# --- Test 1: POST /leagues/{league_id}/members without auth → 401 ---
echo ""
echo "Test 1: POST /leagues/league_open_padel/members without auth → 401"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  "$API/leagues/league_open_padel/members")
if [ "$STATUS" -eq 401 ]; then
  echo "PASS: got 401"
else
  echo "FAIL: expected 401, got $STATUS"
  exit 1
fi

# --- Test 2: DELETE /leagues/{league_id}/members/{uid} without auth → 401 ---
echo ""
echo "Test 2: DELETE /leagues/league_open_padel/members/user_ignatios without auth → 401"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
  "$API/leagues/league_open_padel/members/user_ignatios")
if [ "$STATUS" -eq 401 ]; then
  echo "PASS: got 401"
else
  echo "FAIL: expected 401, got $STATUS"
  exit 1
fi

# --- Test 3: POST /leagues/{league_id}/members as non-admin → 403 ---
echo ""
echo "Test 3: POST /leagues/league_open_padel/members as non-admin → 403"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/league_open_padel/members")
if [ "$STATUS" -eq 403 ]; then
  echo "PASS: got 403"
else
  echo "FAIL: expected 403, got $STATUS"
  exit 1
fi

# --- Test 4: DELETE /leagues/{league_id}/members/{uid} as non-admin → 403 ---
echo ""
echo "Test 4: DELETE /leagues/league_open_padel/members/user_other as non-admin → 403"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/league_open_padel/members/user_other")
if [ "$STATUS" -eq 403 ]; then
  echo "PASS: got 403"
else
  echo "FAIL: expected 403, got $STATUS"
  exit 1
fi

# --- Test 5: GET /leagues still works (regression check) → 200 ---
echo ""
echo "Test 5: GET /leagues with auth → 200 (regression check)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues")
if [ "$STATUS" -eq 200 ]; then
  echo "PASS: got 200"
else
  echo "FAIL: expected 200, got $STATUS"
  exit 1
fi

echo ""
echo "=== All PR #302 smoke tests passed ==="
