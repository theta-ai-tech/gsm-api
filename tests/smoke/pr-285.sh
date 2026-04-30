#!/usr/bin/env bash
# Smoke tests for PR #285: feat: DBL-4 extend offer + acceptance flow for doubles (#168)
# Generated: 2026-04-27
# Usage: bash tests/smoke/pr-285.sh
#
# Requires: make emu-all + make api-dev-emu-auth running
#
# This script exercises POST /me/offers with the new match_type / partner_uid
# fields, the broadcast/offer match_type matching rule, and the doubles
# acceptance flow. It is self-contained: the test user (user_ignatios) and the
# recipient (user_alice) cancel any active broadcast/offer before each scenario
# and on exit, so repeated runs converge.
#
# The 4-player happy path needs a 4th seeded user (user_bob is the broadcaster's
# partner); the challenger's partner is user_ignatios's hypothetical 4th. Since
# tools/seed_data.py only seeds ignatios/alice/bob, the doubles-acceptance test
# uses ignatios=challenger, alice=broadcaster, bob=alice's partner, and creates
# a 4th user document directly in the Firestore emulator.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://localhost:8000}"
FIRESTORE_HOST_PORT="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
FIRESTORE_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FIRESTORE="http://${FIRESTORE_HOST_PORT}/v1/projects/${FIRESTORE_PROJECT}/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR (or $REPO_ROOT/.venv). Run 'make venv && make install' in the main checkout."
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

# ── Token acquisition ───────────────────────────────────────────────────────
IGGY=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
ALICE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
BOB=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_bob -t 2>/dev/null)
if [ -z "$IGGY" ] || [ -z "$ALICE" ] || [ -z "$BOB" ]; then
  echo "ERROR: Could not get auth tokens for seeded users. Is the auth emulator running?"
  exit 1
fi

reset_playtab() {
  # Reset playTab to DISCOVERY for the four test users so the smoke script is
  # idempotent across runs. Tests 3 and 11 leave users in MATCH_SCHEDULED, which
  # would otherwise block subsequent broadcasts/offers and cascade into 409s on
  # tests 6/7/8/9. Direct Firestore PATCH (no auth required against emulator).
  for uid in user_ignatios user_alice user_bob user_charlie; do
    curl -s -o /dev/null -X PATCH \
      "$FIRESTORE/users/$uid?updateMask.fieldPaths=playTab" \
      -H "Content-Type: application/json" \
      -d '{
        "fields": {
          "playTab": {
            "mapValue": {
              "fields": {
                "state": {"stringValue": "DISCOVERY"},
                "activeBroadcastId": {"nullValue": null},
                "activeOutgoingOfferId": {"nullValue": null},
                "activeMatchId": {"nullValue": null},
                "pendingIncomingOfferIds": {"arrayValue": {"values": []}}
              }
            }
          }
        }
      }' || true
  done
}

cleanup() {
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $IGGY" "$API/me/broadcast" || true
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $ALICE" "$API/me/broadcast" || true
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $BOB" "$API/me/broadcast" || true
  reset_playtab
}
trap cleanup EXIT
cleanup

PROPOSED_TIME="2099-12-31T18:00:00Z"

# ── Tests ───────────────────────────────────────────────────────────────────

# Test 1: Singles offer regression — match_type defaults to singles
echo "Test 1: Alice broadcasts singles, Iggy challenges → match_type=singles, partner_uid=null"
BROADCAST_ID=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE" -H "Content-Type: application/json" \
  -d "{
    \"sport\":\"tennis\",
    \"availability\":\"today\",
    \"court_status\":\"need_court\",
    \"expires_at\":\"2099-01-01T00:00:00Z\",
    \"location\":{\"area\":10001}
  }" | jq -r '.broadcast_id')
assert_eq "broadcast created" "$([ -n "$BROADCAST_ID" ] && [ "$BROADCAST_ID" != "null" ] && echo ok)" "ok"

OFFER=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" -H "Content-Type: application/json" \
  -d "{
    \"to_uid\":\"user_alice\",
    \"sport\":\"tennis\",
    \"proposed_time\":\"$PROPOSED_TIME\",
    \"source_broadcast_id\":\"$BROADCAST_ID\"
  }")
assert_eq "match_type=singles" "$(echo "$OFFER" | jq -r '.match_type')" "singles"
assert_eq "partner_uid is null" "$(echo "$OFFER" | jq -r '.partner_uid')" "null"

OFFER_ID=$(echo "$OFFER" | jq -r '.offer_id')

echo "Test 2: Singles offer doc on Firestore carries matchType=singles, partnerUid=null"
DOC=$(curl -s "$FIRESTORE/offers/$OFFER_ID")
assert_eq "doc.matchType=singles" "$(echo "$DOC" | jq -r '.fields.matchType.stringValue')" "singles"
# partnerUid is null → Firestore stores nullValue. Either the field is present with
# a nullValue marker (Python SDK persists None) or absent entirely. We accept both:
# what we explicitly forbid is partnerUid carrying a stringValue for a singles offer.
PARTNER_STR=$(echo "$DOC" | jq -r '.fields.partnerUid.stringValue // "absent"')
assert_eq "doc.partnerUid has no stringValue (singles)" "$PARTNER_STR" "absent"

echo "Test 3: Singles acceptance still creates a 2-player match (regression)"
ACCEPT=$(curl -s -X POST "$API/me/offers/$OFFER_ID/accept" -H "Authorization: Bearer $ALICE")
MATCH_ID=$(echo "$ACCEPT" | jq -r '.match_id // empty')
if [ -z "$MATCH_ID" ]; then
  # Fall back to /me/state to fetch it
  MATCH_ID=$(curl -s -H "Authorization: Bearer $ALICE" "$API/me/state" | jq -r '.payload.active_match_id // empty')
fi
MDOC=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "match.matchType=singles" "$(echo "$MDOC" | jq -r '.fields.matchType.stringValue')" "singles"
assert_eq "match.participantUids length=2" "$(echo "$MDOC" | jq -r '.fields.participantUids.arrayValue.values | length')" "2"

cleanup

# Test 4: Singles offer with partner_uid → 422
echo "Test 4: Singles offer with partner_uid is rejected (422)"
ALICE_BC=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE" -H "Content-Type: application/json" \
  -d "{
    \"sport\":\"tennis\",
    \"availability\":\"today\",
    \"court_status\":\"need_court\",
    \"expires_at\":\"2099-01-01T00:00:00Z\",
    \"location\":{\"area\":10001}
  }" | jq -r '.broadcast_id')
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" -H "Content-Type: application/json" \
  -d "{
    \"to_uid\":\"user_alice\",
    \"sport\":\"tennis\",
    \"partner_uid\":\"user_bob\",
    \"proposed_time\":\"$PROPOSED_TIME\",
    \"source_broadcast_id\":\"$ALICE_BC\"
  }")
assert_eq "singles+partner_uid → 422" "$HTTP" "422"

# Test 5: Doubles offer without partner_uid → 422
echo "Test 5: Doubles offer without partner_uid is rejected (422)"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" -H "Content-Type: application/json" \
  -d "{
    \"to_uid\":\"user_alice\",
    \"sport\":\"tennis\",
    \"match_type\":\"doubles\",
    \"proposed_time\":\"$PROPOSED_TIME\",
    \"source_broadcast_id\":\"$ALICE_BC\"
  }")
assert_eq "doubles without partner_uid → 422" "$HTTP" "422"

# Test 6: Doubles offer to a singles broadcast → 400 (match_type mismatch)
echo "Test 6: Doubles offer to a singles broadcast returns 400"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" -H "Content-Type: application/json" \
  -d "{
    \"to_uid\":\"user_alice\",
    \"sport\":\"tennis\",
    \"match_type\":\"doubles\",
    \"partner_uid\":\"user_bob\",
    \"proposed_time\":\"$PROPOSED_TIME\",
    \"source_broadcast_id\":\"$ALICE_BC\"
  }")
assert_eq "doubles → singles broadcast → 400" "$HTTP" "400"

cleanup

# Test 7: Singles offer to a doubles broadcast → 400
echo "Test 7: Singles offer to a doubles broadcast returns 400"
DBL_BC=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE" -H "Content-Type: application/json" \
  -d "{
    \"sport\":\"padel\",
    \"match_type\":\"doubles\",
    \"broadcast_type\":\"find_opponent\",
    \"partner_uid\":\"user_bob\",
    \"availability\":\"today\",
    \"court_status\":\"need_court\",
    \"expires_at\":\"2099-01-01T00:00:00Z\",
    \"location\":{\"area\":10001}
  }" | jq -r '.broadcast_id')
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" -H "Content-Type: application/json" \
  -d "{
    \"to_uid\":\"user_alice\",
    \"sport\":\"padel\",
    \"proposed_time\":\"$PROPOSED_TIME\",
    \"source_broadcast_id\":\"$DBL_BC\"
  }")
assert_eq "singles → doubles broadcast → 400" "$HTTP" "400"

# Test 8: Doubles offer with non-existent partner_uid → 400
echo "Test 8: Doubles offer with non-existent partner_uid returns 400"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" -H "Content-Type: application/json" \
  -d "{
    \"to_uid\":\"user_alice\",
    \"sport\":\"padel\",
    \"match_type\":\"doubles\",
    \"partner_uid\":\"user_does_not_exist\",
    \"proposed_time\":\"$PROPOSED_TIME\",
    \"source_broadcast_id\":\"$DBL_BC\"
  }")
assert_eq "doubles + bad partner → 400" "$HTTP" "400"

# Test 9: Doubles offer with all-distinct UIDs persists matchType + partnerUid
# Seed a 4th user (user_charlie) directly in the emulator since seed_data only
# has 3 users. We only need users/{uid} to exist for the partner-exists check.
echo "Test 9: Seed user_charlie + doubles offer succeeds with matchType=doubles"
curl -s -o /dev/null -X PATCH "$FIRESTORE/users/user_charlie" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "uid": {"stringValue": "user_charlie"},
      "name": {"stringValue": "Charlie Test"},
      "email": {"stringValue": "charlie@gsm.local"}
    }
  }'

DBL_OFFER=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" -H "Content-Type: application/json" \
  -d "{
    \"to_uid\":\"user_alice\",
    \"sport\":\"padel\",
    \"match_type\":\"doubles\",
    \"partner_uid\":\"user_charlie\",
    \"proposed_time\":\"$PROPOSED_TIME\",
    \"source_broadcast_id\":\"$DBL_BC\"
  }")
assert_eq "doubles offer match_type=doubles" "$(echo "$DBL_OFFER" | jq -r '.match_type')" "doubles"
assert_eq "doubles offer partner_uid=user_charlie" "$(echo "$DBL_OFFER" | jq -r '.partner_uid')" "user_charlie"

DBL_OFFER_ID=$(echo "$DBL_OFFER" | jq -r '.offer_id')
echo "Test 10: Doubles offer doc carries matchType=doubles, partnerUid=user_charlie"
DOC=$(curl -s "$FIRESTORE/offers/$DBL_OFFER_ID")
assert_eq "doc.matchType=doubles" "$(echo "$DOC" | jq -r '.fields.matchType.stringValue')" "doubles"
assert_eq "doc.partnerUid=user_charlie" "$(echo "$DOC" | jq -r '.fields.partnerUid.stringValue')" "user_charlie"

# Test 11: Accepting the doubles offer creates a 4-player match
echo "Test 11: Doubles acceptance creates 4-player match with team A/B"
ACCEPT=$(curl -s -X POST "$API/me/offers/$DBL_OFFER_ID/accept" -H "Authorization: Bearer $ALICE")
MATCH_ID=$(echo "$ACCEPT" | jq -r '.match_id // empty')
if [ -z "$MATCH_ID" ]; then
  MATCH_ID=$(curl -s -H "Authorization: Bearer $ALICE" "$API/me/state" | jq -r '.payload.active_match_id // empty')
fi
MDOC=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "match.matchType=doubles" "$(echo "$MDOC" | jq -r '.fields.matchType.stringValue')" "doubles"
assert_eq "match.participantUids length=4" "$(echo "$MDOC" | jq -r '.fields.participantUids.arrayValue.values | length')" "4"

# Verify team labels — Team A should have 2 entries, Team B should have 2 entries
TEAM_A=$(echo "$MDOC" | jq -r '[.fields.participants.arrayValue.values[] | select(.mapValue.fields.team.stringValue == "A")] | length')
TEAM_B=$(echo "$MDOC" | jq -r '[.fields.participants.arrayValue.values[] | select(.mapValue.fields.team.stringValue == "B")] | length')
assert_eq "Team A has 2 players" "$TEAM_A" "2"
assert_eq "Team B has 2 players" "$TEAM_B" "2"

# Verify all 4 participants flipped to MATCH_SCHEDULED
echo "Test 12: All 4 participants are in MATCH_SCHEDULED"
for uid in user_ignatios user_alice user_bob user_charlie; do
  STATE=$(curl -s "$FIRESTORE/users/$uid")
  assert_eq "$uid playTab.state=MATCH_SCHEDULED" \
    "$(echo "$STATE" | jq -r '.fields.playTab.mapValue.fields.state.stringValue')" \
    "MATCH_SCHEDULED"
done

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #285: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
