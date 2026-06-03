#!/usr/bin/env bash
# Smoke tests for PR #333: feat: LGM-1 thread leagueId through offer→match creation flow (#322)
# Generated: 2026-06-02
# Usage: bash tests/smoke/pr-333.sh
#
# Requires: make emu-all + make seed-emu running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8333}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

LEAGUE_ID="padel-local-2025"
USER_A="user_ignatios"   # ACTIVE member of padel-local-2025
USER_B="user_bob"        # ACTIVE member of padel-local-2025
USER_NON_MEMBER="user_smoke_333_nonmember"  # fresh uid — not a league member

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

assert_not_null() {
  local name="$1" actual="$2"
  if [ -n "$actual" ] && [ "$actual" != "null" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (got null/empty)"
    ((FAIL++)) || true
  fi
}

reset_play_tab() {
  local uid="$1"
  curl -s -X PATCH \
    "$FIRESTORE/users/$uid?updateMask.fieldPaths=playTab.state&updateMask.fieldPaths=playTab.activeBroadcastId&updateMask.fieldPaths=playTab.activeMatchId&updateMask.fieldPaths=playTab.activeOutgoingOfferId&updateMask.fieldPaths=playTab.pendingIncomingOfferIds" \
    -H "Content-Type: application/json" \
    -d '{
      "fields": {
        "playTab": {
          "mapValue": {
            "fields": {
              "state": {"stringValue": "DISCOVERY"},
              "activeBroadcastId": {"nullValue": null},
              "activeMatchId": {"nullValue": null},
              "activeOutgoingOfferId": {"nullValue": null},
              "pendingIncomingOfferIds": {"arrayValue": {}}
            }
          }
        }
      }
    }' > /dev/null
}

firestore_get_string() {
  # Usage: firestore_get_string <collection/docId> <field>
  curl -s "$FIRESTORE/$1" | jq -r ".fields.$2.stringValue // \"null\""
}

# ── Token acquisition ────────────────────────────────────────────────────────
# Robust helper: looks up the user's existing Auth email (handles emulator
# restarts where seeded users have gsm.local emails), falling back to creating
# a fresh account with @example.com for users that don't exist yet.
get_token_for_uid() {
  local uid="$1"
  local fallback_email="${uid}@example.com"
  local password="test_pass_123"
  local auth_host="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
  local existing_email
  existing_email=$(curl -s -X POST \
    "http://${auth_host}/identitytoolkit.googleapis.com/v1/accounts:lookup?key=fake-api-key" \
    -H "Authorization: Bearer owner" \
    -H "Content-Type: application/json" \
    -d "{\"localId\": [\"$uid\"]}" | jq -r '.users[0].email // empty' 2>/dev/null || true)
  local email="${existing_email:-$fallback_email}"
  bash "$REPO_ROOT/scripts/get_emu_token.sh" "$uid" "$email" "$password" -t 2>/dev/null
}

echo "Acquiring tokens..."
TOKEN_A=$(get_token_for_uid "$USER_A")
TOKEN_B=$(get_token_for_uid "$USER_B")
TOKEN_NON=$(get_token_for_uid "$USER_NON_MEMBER")

if [ -z "$TOKEN_A" ] || [ -z "$TOKEN_B" ]; then
  echo "ERROR: Could not get auth tokens. Are emulators running and seed applied?"
  exit 1
fi
echo "  Tokens acquired."
echo ""

# ── Setup: reset both seeded users to DISCOVERY ─────────────────────────────
echo "Setup: resetting play states to DISCOVERY..."
reset_play_tab "$USER_A"
reset_play_tab "$USER_B"
echo "  Done."
echo ""

OFFER_ID="null"
MATCH_ID="null"

# ── Step 1: Send a league-scoped offer ──────────────────────────────────────
echo "=== Step 1: POST /me/offers with leagueId creates offer (201) ==="
PROPOSED_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OFFER_RESP=$(curl -s -o /tmp/pr333_offer.json -w "%{http_code}" \
  -X POST "$API/me/offers" \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"$USER_B\",
    \"sport\": \"padel\",
    \"match_type\": \"singles\",
    \"proposed_time\": \"$PROPOSED_TIME\",
    \"league_id\": \"$LEAGUE_ID\"
  }")
assert_eq "POST /me/offers returns 201" "$OFFER_RESP" "201"

OFFER_ID=$(jq -r '.offer_id // "null"' /tmp/pr333_offer.json)
assert_not_null "Offer ID is present" "$OFFER_ID"
echo "  offer_id: $OFFER_ID"

# Verify leagueId was stored on the offer doc in Firestore
OFFER_LEAGUE=$(firestore_get_string "offers/$OFFER_ID" "leagueId")
assert_eq "Offer doc has leagueId in Firestore" "$OFFER_LEAGUE" "$LEAGUE_ID"

echo ""
echo "=== Step 2: Accept the offer as user B ==="
ACCEPT_RESP=$(curl -s -o /tmp/pr333_accept.json -w "%{http_code}" \
  -X POST "$API/me/offers/$OFFER_ID/accept" \
  -H "Authorization: Bearer $TOKEN_B")
assert_eq "POST /me/offers/{id}/accept returns 200" "$ACCEPT_RESP" "200"

MATCH_ID=$(jq -r '.match_id // "null"' /tmp/pr333_accept.json)
assert_not_null "Match ID is present in accept response" "$MATCH_ID"
echo "  match_id: $MATCH_ID"

echo ""
echo "=== Step 3: Match document has leagueId set in Firestore ==="
MATCH_LEAGUE=$(firestore_get_string "matches/$MATCH_ID" "leagueId")
assert_eq "Match doc has leagueId = $LEAGUE_ID" "$MATCH_LEAGUE" "$LEAGUE_ID"

echo ""
echo "=== Step 4: GET /leagues/{id}/matches lists the match ==="
LEAGUES_MATCHES=$(curl -s \
  "$API/leagues/$LEAGUE_ID/matches" \
  -H "Authorization: Bearer $TOKEN_A")
FOUND_MATCH=$(echo "$LEAGUES_MATCHES" | jq -r --arg mid "$MATCH_ID" '
  (.matches // []) | .[] | select(.match_id == $mid) | .league_id // "null"' 2>/dev/null || echo "null")
assert_eq "League matches list includes new match with leagueId" "$FOUND_MATCH" "$LEAGUE_ID"

echo ""
echo "=== Step 5: Non-member offer is rejected (409) ==="
# Reset USER_B to DISCOVERY (was in MATCH_SCHEDULED after step 2)
reset_play_tab "$USER_B"
# Create a Firestore profile for the non-member so they pass the sender-exists check
curl -s -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN_NON" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Non Member\",\"sports\":[\"padel\"],\"levels\":{\"padel\":\"beginner\"},\"area\":1}" \
  > /dev/null 2>&1 || true

NON_MEMBER_RESP=$(curl -s -o /tmp/pr333_nonmember.json -w "%{http_code}" \
  -X POST "$API/me/offers" \
  -H "Authorization: Bearer $TOKEN_NON" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"$USER_B\",
    \"sport\": \"padel\",
    \"match_type\": \"singles\",
    \"proposed_time\": \"$PROPOSED_TIME\",
    \"league_id\": \"$LEAGUE_ID\"
  }")
assert_eq "Non-member offer returns 409" "$NON_MEMBER_RESP" "409"

echo ""
echo "=== Step 6: Non-existent league is rejected (400) ==="
# Reset USER_A to DISCOVERY (accepted offer may have changed state)
reset_play_tab "$USER_A"
FAKE_LEAGUE_RESP=$(curl -s -o /tmp/pr333_fakelg.json -w "%{http_code}" \
  -X POST "$API/me/offers" \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"$USER_B\",
    \"sport\": \"padel\",
    \"match_type\": \"singles\",
    \"proposed_time\": \"$PROPOSED_TIME\",
    \"league_id\": \"does-not-exist-league\"
  }")
assert_eq "Nonexistent league returns 404" "$FAKE_LEAGUE_RESP" "404"

# ── Teardown ─────────────────────────────────────────────────────────────────
echo ""
echo "Teardown: cleaning up match + offer docs and resetting play states..."
[ "$MATCH_ID" != "null" ] && \
  curl -s -X DELETE "$FIRESTORE/matches/$MATCH_ID" > /dev/null 2>&1 || true
[ "$OFFER_ID" != "null" ] && \
  curl -s -X DELETE "$FIRESTORE/offers/$OFFER_ID" > /dev/null 2>&1 || true
curl -s -X DELETE "$FIRESTORE/users/$USER_NON_MEMBER" > /dev/null 2>&1 || true
reset_play_tab "$USER_A"
reset_play_tab "$USER_B"
echo "  Done."

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #333: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
