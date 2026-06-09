#!/usr/bin/env bash
# Smoke tests for PR #335: docs: LGM-3 add league endpoints to frozen mobile contract + wiki (#324)
# Generated: 2026-06-09
# Usage: bash tests/smoke/pr-335.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8335}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"
LEAGUE_ID="test-league-lgm3-335"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="${MAIN_WT}/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# ── Helpers ──────────────────────────────────────────────────────────────────

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

assert_not_eq() {
  local name="$1" actual="$2" unexpected="$3"
  if [ "$actual" != "$unexpected" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    got unexpected value: $actual"
    ((FAIL++)) || true
  fi
}

# ── Token acquisition ────────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Seed: create league ──────────────────────────────────────────────────────
echo ""
echo "── Setup ──────────────────────────────────────────────────────────────"

# Delete any leftover from a previous run (ignore errors)
curl -s -X DELETE "$FIRESTORE/leagues/$LEAGUE_ID" > /dev/null 2>&1 || true
curl -s -X DELETE "$FIRESTORE/leagues/$LEAGUE_ID/members/user_ignatios" > /dev/null 2>&1 || true

curl -s -X POST \
  "$FIRESTORE/leagues?documentId=$LEAGUE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "name":            {"stringValue": "Test League LGM-3"},
      "sport":           {"stringValue": "padel"},
      "status":          {"stringValue": "open"},
      "owner_uid":       {"stringValue": "user_ignatios"},
      "max_players":     {"integerValue": "16"},
      "current_players": {"integerValue": "0"},
      "region":          {"stringValue": "athens"},
      "tier":            {"stringValue": "intermediate"}
    }
  }' > /dev/null
echo "  seeded league: $LEAGUE_ID"

# ── Tests ────────────────────────────────────────────────────────────────────
echo ""
echo "── Tests ───────────────────────────────────────────────────────────────"

# 1. Browse leagues — GET /leagues?sport=padel&status=open
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues?sport=padel&status=open" \
  | jq -r '[.leagues[] | select(.league_id == "'"$LEAGUE_ID"'")] | length | tostring')
assert_eq "GET /leagues — seeded league appears in browse results" "$ACTUAL" "1"

# 2. Get league detail — GET /leagues/{id}
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$LEAGUE_ID" \
  | jq -r '.league_id // "null"')
assert_eq "GET /leagues/{id} — returns correct league_id" "$ACTUAL" "$LEAGUE_ID"

ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$LEAGUE_ID" \
  | jq -r '.sport // "null"')
assert_eq "GET /leagues/{id} — sport field present" "$ACTUAL" "padel"

# 3. Join league — POST /leagues/{id}/join
HTTP_CODE=$(curl -s -o /tmp/join_response_335.json -w "%{http_code}" \
  -X POST -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$LEAGUE_ID/join")
assert_eq "POST /leagues/{id}/join — returns 201" "$HTTP_CODE" "201"

ACTUAL=$(jq -r '.role // "null"' /tmp/join_response_335.json)
assert_eq "POST /leagues/{id}/join — role is player" "$ACTUAL" "player"

ACTUAL=$(jq -r '.status // "null"' /tmp/join_response_335.json)
assert_eq "POST /leagues/{id}/join — member status is active" "$ACTUAL" "active"

# 3b. Joining again should 409
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$LEAGUE_ID/join")
assert_eq "POST /leagues/{id}/join — duplicate join returns 409" "$HTTP_CODE" "409"

# 4. Get standings (as member) — GET /leagues/{id}/standings
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$LEAGUE_ID/standings" \
  | jq -r '.league_id // "null"')
assert_eq "GET /leagues/{id}/standings — returns correct league_id" "$ACTUAL" "$LEAGUE_ID"

ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$LEAGUE_ID/standings" \
  | jq -r '.standings | type')
assert_eq "GET /leagues/{id}/standings — standings is an array" "$ACTUAL" "array"

# 5. Get matches (as member) — GET /leagues/{id}/matches?type=upcoming
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$LEAGUE_ID/matches?type=upcoming" \
  | jq -r '.matches | type')
assert_eq "GET /leagues/{id}/matches — matches field is an array" "$ACTUAL" "array"

# 5b. Non-member access to standings should 403
# (use a second token if available; skip if only one user seeded)
TOKEN2=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_sam -t 2>/dev/null || true)
if [ -n "$TOKEN2" ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN2" \
    "$API/leagues/$LEAGUE_ID/standings")
  assert_eq "GET /leagues/{id}/standings — non-member gets 403" "$HTTP_CODE" "403"
fi

# 6. Send offer with league_id — verify field is accepted (not 422)
# user_ignatios must be in DISCOVERY state. After joining, state is still DISCOVERY
# (join doesn't change play state). We attempt the offer and verify it's not rejected
# as an unknown field (422). A 404 (user not found) or 409 (state conflict) is acceptable.
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$API/me/offers" \
  -d "{\"to_uid\":\"user_sam\",\"sport\":\"padel\",\"match_type\":\"singles\",\"proposed_time\":\"2026-07-01T18:00:00Z\",\"league_id\":\"$LEAGUE_ID\"}")
assert_not_eq "POST /me/offers with league_id — field accepted (not 422)" "$HTTP_CODE" "422"

# ── Teardown ─────────────────────────────────────────────────────────────────
echo ""
echo "── Teardown ────────────────────────────────────────────────────────────"
curl -s -X DELETE "$FIRESTORE/leagues/$LEAGUE_ID/members/user_ignatios" > /dev/null 2>&1 || true
curl -s -X DELETE "$FIRESTORE/leagues/$LEAGUE_ID" > /dev/null 2>&1 || true
rm -f /tmp/join_response_335.json
echo "  cleaned up league: $LEAGUE_ID"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #335: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
