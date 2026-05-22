#!/usr/bin/env bash
# Smoke tests for PR #305: feat: LG-10 add POST /leagues/{leagueId}/join — self-serve join flow (#257)
# Generated: 2026-05-20
# Usage: bash tests/smoke/pr-305.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8305}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# Temporary league created at test start — fully self-contained, no seeded state dependency
SMOKE_LEAGUE="smoke-test-join-305"

# Seeded league with ACTIVE status — used for wrong-status 409 test
ACTIVE_LEAGUE="padel-local-2025"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2 ; exit}')
  VENV_DIR="$MAIN_WT/.venv"
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

# ── Setup: create a temporary OPEN league in the emulator ───────────────────
echo "Setup: creating temporary OPEN league '$SMOKE_LEAGUE' in emulator..."
SETUP_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
  "$FIRESTORE/leagues/$SMOKE_LEAGUE?updateMask.fieldPaths=name&updateMask.fieldPaths=sport&updateMask.fieldPaths=status&updateMask.fieldPaths=ownerUid&updateMask.fieldPaths=maxPlayers&updateMask.fieldPaths=currentPlayers&updateMask.fieldPaths=region" \
  -H "Content-Type: application/json" \
  -d '{"fields":{"name":{"stringValue":"Smoke Test Join League 305"},"sport":{"stringValue":"padel"},"status":{"stringValue":"open"},"ownerUid":{"stringValue":"user_alice"},"maxPlayers":{"integerValue":"10"},"currentPlayers":{"integerValue":"0"},"region":{"stringValue":"athens"}}}')
if [ "$SETUP_RESP" != "200" ]; then
  echo "ABORT: Failed to create smoke league in emulator (HTTP $SETUP_RESP). Is the Firestore emulator running?"
  exit 1
fi
echo "  Smoke league created (HTTP $SETUP_RESP)."

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

echo ""
echo "Smoke tests — PR #305: POST /leagues/{leagueId}/join"
echo "────────────────────────────────────────────────────"

# ── Test 1: Happy path — join an OPEN league → 201 ─────────────────────────
echo ""
echo "Test 1: Happy path — join OPEN league"
RESP=$(curl -s -o /tmp/pr305_join.json -w "%{http_code}" \
  -X POST "$API/leagues/$SMOKE_LEAGUE/join" \
  -H "Authorization: Bearer $TOKEN")
assert_eq "POST /leagues/$SMOKE_LEAGUE/join returns 201" "$RESP" "201"

ROLE=$(jq -r '.role // "null"' /tmp/pr305_join.json)
assert_eq "response.role = player" "$ROLE" "player"

STATUS=$(jq -r '.status // "null"' /tmp/pr305_join.json)
assert_eq "response.status = active" "$STATUS" "active"

UID_FIELD=$(jq -r '.uid // "null"' /tmp/pr305_join.json)
assert_eq "response.uid is present" "$([ -n "$UID_FIELD" ] && [ "$UID_FIELD" != "null" ] && echo "ok" || echo "missing")" "ok"

JOINED_AT=$(jq -r '.joined_at // "null"' /tmp/pr305_join.json)
assert_eq "response.joined_at is present" "$([ "$JOINED_AT" != "null" ] && echo "ok" || echo "missing")" "ok"

# ── Test 2: Already a member → 409 ─────────────────────────────────────────
echo ""
echo "Test 2: Already a member → 409"
RESP2=$(curl -s -o /tmp/pr305_dup.json -w "%{http_code}" \
  -X POST "$API/leagues/$SMOKE_LEAGUE/join" \
  -H "Authorization: Bearer $TOKEN")
assert_eq "duplicate join returns 409" "$RESP2" "409"

DETAIL2=$(jq -r '.detail // "null"' /tmp/pr305_dup.json)
assert_eq "409 detail mentions 'already a member'" \
  "$(echo "$DETAIL2" | grep -c 'already a member' || true)" "1"

# ── Test 3: League not found → 404 ─────────────────────────────────────────
echo ""
echo "Test 3: League not found → 404"
RESP3=$(curl -s -o /tmp/pr305_notfound.json -w "%{http_code}" \
  -X POST "$API/leagues/nonexistent_league_xyz/join" \
  -H "Authorization: Bearer $TOKEN")
assert_eq "nonexistent league returns 404" "$RESP3" "404"

DETAIL3=$(jq -r '.detail // "null"' /tmp/pr305_notfound.json)
assert_eq "404 detail mentions 'not found'" \
  "$(echo "$DETAIL3" | grep -c 'not found' || true)" "1"

# ── Test 4: Wrong status (ACTIVE league) → 409 ─────────────────────────────
echo ""
echo "Test 4: Wrong status (ACTIVE league) → 409"
RESP4=$(curl -s -o /tmp/pr305_badstatus.json -w "%{http_code}" \
  -X POST "$API/leagues/$ACTIVE_LEAGUE/join" \
  -H "Authorization: Bearer $TOKEN")
assert_eq "ACTIVE league join returns 409" "$RESP4" "409"

DETAIL4=$(jq -r '.detail // "null"' /tmp/pr305_badstatus.json)
assert_eq "409 detail mentions status" \
  "$(echo "$DETAIL4" | grep -cE 'status|OPEN|UPCOMING' || true)" "1"

# ── Test 5: No auth → 401 ─────────────────────────────────────────────────
echo ""
echo "Test 5: No auth → 401"
RESP5=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$API/leagues/$SMOKE_LEAGUE/join")
assert_eq "missing auth returns 401" "$RESP5" "401"

# ── Teardown ────────────────────────────────────────────────────────────────
# Delete the temporary smoke league and its members subcollection entry.
echo ""
echo "Teardown: deleting temporary smoke league '$SMOKE_LEAGUE'..."
curl -s -o /dev/null -X DELETE \
  "$FIRESTORE/leagues/$SMOKE_LEAGUE/members/user_ignatios" || true
DEL_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
  "$FIRESTORE/leagues/$SMOKE_LEAGUE")
echo "  Teardown complete (DELETE league HTTP=$DEL_RESP)."

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #305: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
