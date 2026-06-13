#!/usr/bin/env bash
# Smoke tests for PR #334: test: LGM-2 integration test — leagueId reaches scoring + standings (#323)
# Generated: 2026-06-09
# Usage: bash tests/smoke/pr-334.sh
#
# NOTE: This is a standings-endpoint smoke test only.
# It verifies that GET /leagues/{id}/standings returns correct ordering when member
# stats are seeded directly via the Firestore emulator REST API.
# It does NOT exercise the full LGM-2 end-to-end flow (offer → accept →
# verify-score → trigger → standings). That flow is covered by the integration
# tests in tests/integration/test_lgm2_league_match_scoring_integration.py
# and can be run with: make test-int
#
# Requires: make emu-all running + API started from the PR worktree.
# The smoke-test skill starts the API automatically.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8334}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

_SMOKE_LEAGUE_ID="smoke-test-lgm2-334"

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
  local name="$1" actual="$2" substring="$3"
  if echo "$actual" | grep -q "$substring"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected to contain: $substring"
    echo "    actual: $actual"
    ((FAIL++)) || true
  fi
}

# ── Token acquisition ────────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token. Is the auth emulator running?"
  exit 1
fi

# ── Setup: seed smoke test league + members via Firestore REST ───────────────

# Seed league doc with status=active so the standings endpoint returns 200.
echo ""
echo "── Setup ──────────────────────────────────────────────────────────────────"

NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
curl -s -X PATCH \
  "$FIRESTORE/leagues/$_SMOKE_LEAGUE_ID?updateMask.fieldPaths=name&updateMask.fieldPaths=sport&updateMask.fieldPaths=status&updateMask.fieldPaths=ownerUid&updateMask.fieldPaths=region&updateMask.fieldPaths=maxPlayers&updateMask.fieldPaths=currentPlayers&updateMask.fieldPaths=startDate" \
  -H "Content-Type: application/json" \
  -d "{
    \"fields\": {
      \"name\": {\"stringValue\": \"Smoke Test LGM-2 League\"},
      \"sport\": {\"stringValue\": \"padel\"},
      \"status\": {\"stringValue\": \"active\"},
      \"ownerUid\": {\"stringValue\": \"smoke_user_a\"},
      \"region\": {\"stringValue\": \"athens\"},
      \"maxPlayers\": {\"integerValue\": \"10\"},
      \"currentPlayers\": {\"integerValue\": \"2\"},
      \"startDate\": {\"timestampValue\": \"$NOW_ISO\"}
    }
  }" > /dev/null
echo "  seeded league doc: $_SMOKE_LEAGUE_ID"

# Seed user_ignatios as an ACTIVE member (required for 200 from standings endpoint).
curl -s -X PATCH \
  "$FIRESTORE/leagues/$_SMOKE_LEAGUE_ID/members/user_ignatios?updateMask.fieldPaths=role&updateMask.fieldPaths=status&updateMask.fieldPaths=joinedAt" \
  -H "Content-Type: application/json" \
  -d "{
    \"fields\": {
      \"role\": {\"stringValue\": \"player\"},
      \"status\": {\"stringValue\": \"active\"},
      \"joinedAt\": {\"timestampValue\": \"$NOW_ISO\"}
    }
  }" > /dev/null
echo "  seeded member: user_ignatios (active, no stats)"

# Seed a second member with 1 win.
curl -s -X PATCH \
  "$FIRESTORE/leagues/$_SMOKE_LEAGUE_ID/members/smoke_user_a?updateMask.fieldPaths=role&updateMask.fieldPaths=status&updateMask.fieldPaths=joinedAt&updateMask.fieldPaths=stats" \
  -H "Content-Type: application/json" \
  -d "{
    \"fields\": {
      \"role\": {\"stringValue\": \"player\"},
      \"status\": {\"stringValue\": \"active\"},
      \"joinedAt\": {\"timestampValue\": \"$NOW_ISO\"},
      \"stats\": {\"mapValue\": {\"fields\": {
        \"wins\": {\"integerValue\": \"1\"},
        \"losses\": {\"integerValue\": \"0\"}
      }}}
    }
  }" > /dev/null
echo "  seeded member: smoke_user_a (active, wins=1)"

# ── Tests ────────────────────────────────────────────────────────────────────

echo ""
echo "── Tests ──────────────────────────────────────────────────────────────────"

# 1. Standings endpoint returns 200.
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$_SMOKE_LEAGUE_ID/standings")
assert_eq "GET /leagues/{id}/standings returns 200" "$STATUS" "200"

# 2. Standings has 2 entries.
STANDINGS_COUNT=$(curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$_SMOKE_LEAGUE_ID/standings" | jq '.standings | length')
assert_eq "standings has 2 members" "$STANDINGS_COUNT" "2"

# 3. smoke_user_a (wins=1) is ranked #1.
TOP_UID=$(curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$_SMOKE_LEAGUE_ID/standings" \
  | jq -r '[.standings[] | select(.rank == 1)] | .[0].uid')
assert_eq "member with wins=1 is rank 1" "$TOP_UID" "smoke_user_a"

# 4. user_ignatios (no stats → wins=0) is ranked #2.
SECOND_UID=$(curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$_SMOKE_LEAGUE_ID/standings" \
  | jq -r '[.standings[] | select(.rank == 2)] | .[0].uid')
assert_eq "member with wins=0 is rank 2" "$SECOND_UID" "user_ignatios"

# 5. Top member has wins=1, losses=0.
TOP_ENTRY=$(curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$_SMOKE_LEAGUE_ID/standings" \
  | jq '[.standings[] | select(.uid == "smoke_user_a")] | .[0]')
TOP_WINS=$(echo "$TOP_ENTRY" | jq '.wins')
TOP_LOSSES=$(echo "$TOP_ENTRY" | jq '.losses')
assert_eq "rank 1 member has wins=1" "$TOP_WINS" "1"
assert_eq "rank 1 member has losses=0" "$TOP_LOSSES" "0"

# 6. Update user_ignatios stats via Firestore REST (simulating trigger update) → re-check standings.
curl -s -X PATCH \
  "$FIRESTORE/leagues/$_SMOKE_LEAGUE_ID/members/user_ignatios?updateMask.fieldPaths=stats" \
  -H "Content-Type: application/json" \
  -d "{
    \"fields\": {
      \"stats\": {\"mapValue\": {\"fields\": {
        \"wins\": {\"integerValue\": \"2\"},
        \"losses\": {\"integerValue\": \"0\"}
      }}}
    }
  }" > /dev/null

NEW_TOP=$(curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "$API/leagues/$_SMOKE_LEAGUE_ID/standings" \
  | jq -r '[.standings[] | select(.rank == 1)] | .[0].uid')
assert_eq "after stats update user_ignatios (wins=2) is rank 1" "$NEW_TOP" "user_ignatios"

# ── Teardown ─────────────────────────────────────────────────────────────────

echo ""
echo "── Teardown ───────────────────────────────────────────────────────────────"

curl -s -X DELETE "$FIRESTORE/leagues/$_SMOKE_LEAGUE_ID/members/user_ignatios" > /dev/null
curl -s -X DELETE "$FIRESTORE/leagues/$_SMOKE_LEAGUE_ID/members/smoke_user_a" > /dev/null
curl -s -X DELETE "$FIRESTORE/leagues/$_SMOKE_LEAGUE_ID" > /dev/null
echo "  cleaned up smoke test league and member docs"

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "Smoke tests PR #334: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
