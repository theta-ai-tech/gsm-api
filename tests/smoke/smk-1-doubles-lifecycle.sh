#!/usr/bin/env bash
# smk-1-doubles-lifecycle.sh — End-to-end smoke test for the padel doubles match lifecycle
# Issue: SMK-1 (#276)
# Generated: 2026-05-30
#
# Usage:
#   bash tests/smoke/smk-1-doubles-lifecycle.sh
#
# Prerequisites:
#   Terminal 1: make emu-all
#   Terminal 2: make seed-emu && make api-dev-emu-auth
#
# Environment variables (optional overrides):
#   API_BASE_URL          — default http://localhost:8000
#   FIRESTORE_EMULATOR_HOST — default 127.0.0.1:8082
#   GOOGLE_CLOUD_PROJECT  — default gsm-dev-f70d0
#
# Lifecycle covered:
#   1. Alice + Bob create a padel doubles broadcast (Team A)
#   2. Iggy challenges with Charlie as partner (Team B offer)
#   3. Alice accepts the offer
#   4. Verify 4-participant match creation (matchType=doubles, 4 UIDs)
#   5. Verify team assignments (Alice+Bob=A, Iggy+Charlie=B)
#   6. Verify all 4 participants transition to MATCH_SCHEDULED
#   7. Iggy (Team B) submits score: winner_team=B
#   8. Verify intermediate states (Iggy=POST_MATCH_WAITING_OPPONENT, others=POST_MATCH_CONFIRM_REQUIRED)
#   9. Alice (Team A, opposing) confirms: winner_team=B
#  10. Verify match status=completed
#  11. Verify all 4 participants return to DISCOVERY

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
    PASS=$((PASS + 1))
  else
    echo "  ✗ $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    FAIL=$((FAIL + 1))
  fi
}

seed_charlie() {
  # Create user_charlie in the Firestore emulator (not in seed_data.py).
  # The play_service partner-exists check reads users/{uid} — without this doc
  # the doubles offer will 400 with "Partner user not found".
  curl -s -o /dev/null -X PATCH "$FIRESTORE/users/user_charlie" \
    -H "Content-Type: application/json" \
    -d '{
      "fields": {
        "uid": {"stringValue": "user_charlie"},
        "name": {"stringValue": "Charlie Test"},
        "email": {"stringValue": "user_charlie@gsm.local"},
        "playTab": {"mapValue": {"fields": {
          "state": {"stringValue": "DISCOVERY"},
          "activeBroadcastId": {"nullValue": null},
          "activeOutgoingOfferId": {"nullValue": null},
          "activeMatchId": {"nullValue": null},
          "pendingIncomingOfferIds": {"arrayValue": {"values": []}}
        }}},
        "rankings": {"mapValue": {"fields": {
          "padel": {"mapValue": {"fields": {
            "pts": {"integerValue": "1000"},
            "tier": {"stringValue": "amateur"}
          }}}
        }}}
      }
    }'
}

reset_playtab() {
  # Reset playTab to DISCOVERY for all 4 participants so the script is
  # idempotent across runs — previous state leaks would block broadcasts/offers.
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
  # Delete active broadcasts for Alice and Bob (they are the broadcasting pair).
  # Iggy and Charlie may be in OFFER_PENDING — reset_playtab handles those.
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $TOKEN_ALICE" "$API/me/broadcast" || true
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $TOKEN_BOB" "$API/me/broadcast" || true
  reset_playtab
}

# ── Token acquisition ───────────────────────────────────────────────────────
# get_emu_token.sh creates the auth emulator user if it doesn't exist yet.
TOKEN_ALICE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
TOKEN_BOB=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_bob -t 2>/dev/null)
TOKEN_IGGY=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
TOKEN_CHARLIE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_charlie -t 2>/dev/null)

if [ -z "$TOKEN_ALICE" ] || [ -z "$TOKEN_BOB" ] || [ -z "$TOKEN_IGGY" ] || [ -z "$TOKEN_CHARLIE" ]; then
  echo "ERROR: Could not obtain auth tokens for all 4 users. Is the auth emulator running?"
  exit 1
fi

# ── Setup ───────────────────────────────────────────────────────────────────
# Seed user_charlie Firestore doc and reset all 4 to a known state.
seed_charlie
trap cleanup EXIT
cleanup

PROPOSED_TIME="2099-12-31T18:00:00Z"

# ── Step 1: Create doubles broadcast (Alice + Bob) ──────────────────────────
echo ""
echo "── Step 1: Alice creates a padel doubles broadcast (Alice=broadcaster, Bob=partner) ──"

BROADCAST_RESP=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN_ALICE" \
  -H "Content-Type: application/json" \
  -d "{
    \"sport\": \"padel\",
    \"match_type\": \"doubles\",
    \"broadcast_type\": \"find_opponent\",
    \"partner_uid\": \"user_bob\",
    \"availability\": \"today\",
    \"court_status\": \"need_court\",
    \"expires_at\": \"2099-01-01T00:00:00Z\",
    \"location\": {\"area\": 10001}
  }")
BROADCAST_ID=$(echo "$BROADCAST_RESP" | jq -r '.broadcast_id // empty')

assert_eq "broadcast created (id present)" \
  "$([ -n "$BROADCAST_ID" ] && [ "$BROADCAST_ID" != "null" ] && echo ok)" "ok"
assert_eq "broadcast match_type=doubles" \
  "$(echo "$BROADCAST_RESP" | jq -r '.match_type // "null"')" "doubles"

# ── Step 2: Verify broadcast doc in Firestore ──────────────────────────────
echo ""
echo "── Step 2: Verify broadcast doc carries matchType=doubles, partnerUid=user_bob ──"

BC_DOC=$(curl -s "$FIRESTORE/broadcasts/$BROADCAST_ID")
assert_eq "broadcast doc matchType=doubles" \
  "$(echo "$BC_DOC" | jq -r '.fields.matchType.stringValue // "null"')" "doubles"
assert_eq "broadcast doc partnerUid=user_bob" \
  "$(echo "$BC_DOC" | jq -r '.fields.partnerUid.stringValue // "null"')" "user_bob"

# ── Step 3: Create doubles offer (Iggy challenges, Charlie as partner) ──────
echo ""
echo "── Step 3: Iggy sends doubles offer to Alice (Iggy=challenger, Charlie=partner) ──"

OFFER_RESP=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $TOKEN_IGGY" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"user_alice\",
    \"sport\": \"padel\",
    \"match_type\": \"doubles\",
    \"partner_uid\": \"user_charlie\",
    \"proposed_time\": \"$PROPOSED_TIME\",
    \"source_broadcast_id\": \"$BROADCAST_ID\"
  }")
OFFER_ID=$(echo "$OFFER_RESP" | jq -r '.offer_id // empty')

assert_eq "offer created (id present)" \
  "$([ -n "$OFFER_ID" ] && [ "$OFFER_ID" != "null" ] && echo ok)" "ok"
assert_eq "offer match_type=doubles" \
  "$(echo "$OFFER_RESP" | jq -r '.match_type // "null"')" "doubles"
assert_eq "offer partner_uid=user_charlie" \
  "$(echo "$OFFER_RESP" | jq -r '.partner_uid // "null"')" "user_charlie"

# ── Step 4: Verify offer doc in Firestore ──────────────────────────────────
echo ""
echo "── Step 4: Verify offer doc carries matchType=doubles, partnerUid=user_charlie ──"

OFFER_DOC=$(curl -s "$FIRESTORE/offers/$OFFER_ID")
assert_eq "offer doc matchType=doubles" \
  "$(echo "$OFFER_DOC" | jq -r '.fields.matchType.stringValue // "null"')" "doubles"
assert_eq "offer doc partnerUid=user_charlie" \
  "$(echo "$OFFER_DOC" | jq -r '.fields.partnerUid.stringValue // "null"')" "user_charlie"

# ── Step 5: Accept offer (Alice accepts) ────────────────────────────────────
echo ""
echo "── Step 5: Alice accepts the doubles offer ──"

ACCEPT_RESP=$(curl -s -X POST "$API/me/offers/$OFFER_ID/accept" \
  -H "Authorization: Bearer $TOKEN_ALICE")
MATCH_ID=$(echo "$ACCEPT_RESP" | jq -r '.match_id // empty')

# Fall back to /me/state if match_id not in accept response
if [ -z "$MATCH_ID" ] || [ "$MATCH_ID" = "null" ]; then
  MATCH_ID=$(curl -s "$API/me/state" \
    -H "Authorization: Bearer $TOKEN_ALICE" \
    | jq -r '.payload.active_match_id // empty')
fi

assert_eq "accept returns match_id" \
  "$([ -n "$MATCH_ID" ] && [ "$MATCH_ID" != "null" ] && echo ok)" "ok"

# ── Step 6: Verify 4-participant match creation ──────────────────────────────
echo ""
echo "── Step 6: Verify match doc has 4 participants and matchType=doubles ──"

MATCH_DOC=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "match matchType=doubles" \
  "$(echo "$MATCH_DOC" | jq -r '.fields.matchType.stringValue // "null"')" "doubles"
assert_eq "match participantUids length=4" \
  "$(echo "$MATCH_DOC" | jq -r '.fields.participantUids.arrayValue.values | length')" "4"

# ── Step 7: Verify team assignments ─────────────────────────────────────────
echo ""
echo "── Step 7: Verify team assignments (Alice+Bob=A, Iggy+Charlie=B) ──"

TEAM_A_COUNT=$(echo "$MATCH_DOC" | jq -r '[.fields.participants.arrayValue.values[] | select(.mapValue.fields.team.stringValue == "A")] | length')
TEAM_B_COUNT=$(echo "$MATCH_DOC" | jq -r '[.fields.participants.arrayValue.values[] | select(.mapValue.fields.team.stringValue == "B")] | length')
assert_eq "Team A has 2 players" "$TEAM_A_COUNT" "2"
assert_eq "Team B has 2 players" "$TEAM_B_COUNT" "2"

ALICE_TEAM=$(echo "$MATCH_DOC" | jq -r '.fields.participants.arrayValue.values[] | select(.mapValue.fields.uid.stringValue == "user_alice") | .mapValue.fields.team.stringValue')
BOB_TEAM=$(echo "$MATCH_DOC" | jq -r '.fields.participants.arrayValue.values[] | select(.mapValue.fields.uid.stringValue == "user_bob") | .mapValue.fields.team.stringValue')
IGGY_TEAM=$(echo "$MATCH_DOC" | jq -r '.fields.participants.arrayValue.values[] | select(.mapValue.fields.uid.stringValue == "user_ignatios") | .mapValue.fields.team.stringValue')
CHARLIE_TEAM=$(echo "$MATCH_DOC" | jq -r '.fields.participants.arrayValue.values[] | select(.mapValue.fields.uid.stringValue == "user_charlie") | .mapValue.fields.team.stringValue')

assert_eq "Alice is on Team A (broadcaster)" "$ALICE_TEAM" "A"
assert_eq "Bob is on Team A (broadcaster's partner)" "$BOB_TEAM" "A"
assert_eq "Iggy is on Team B (challenger)" "$IGGY_TEAM" "B"
assert_eq "Charlie is on Team B (challenger's partner)" "$CHARLIE_TEAM" "B"

# ── Step 8: Verify all 4 participants in MATCH_SCHEDULED ────────────────────
echo ""
echo "── Step 8: Verify all 4 participants are in MATCH_SCHEDULED ──"

ALICE_STATE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
BOB_STATE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_BOB" | jq -r '.mode // .play_tab.state // "null"')
IGGY_STATE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_IGGY" | jq -r '.mode // .play_tab.state // "null"')
CHARLIE_STATE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_CHARLIE" | jq -r '.mode // .play_tab.state // "null"')

assert_eq "Alice → MATCH_SCHEDULED" "$ALICE_STATE" "MATCH_SCHEDULED"
assert_eq "Bob → MATCH_SCHEDULED" "$BOB_STATE" "MATCH_SCHEDULED"
assert_eq "Iggy → MATCH_SCHEDULED" "$IGGY_STATE" "MATCH_SCHEDULED"
assert_eq "Charlie → MATCH_SCHEDULED" "$CHARLIE_STATE" "MATCH_SCHEDULED"

# ── Step 9: Submit score (Iggy, Team B, declares winner_team=B) ─────────────
echo ""
echo "── Step 9: Iggy (Team B) submits score declaring winner_team=B ──"

SUBMIT_RESP=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_IGGY" \
  -H "Content-Type: application/json" \
  -d '{"winner_team":"B","score":{"sets":[{"p1_games":7,"p2_games":5},{"p1_games":6,"p2_games":4}]}}')

assert_eq "submit → status=pending_confirmation" \
  "$(echo "$SUBMIT_RESP" | jq -r '.status // "null"')" "pending_confirmation"
assert_eq "submit → winner_team=B" \
  "$(echo "$SUBMIT_RESP" | jq -r '.winner_team // "null"')" "B"
assert_eq "submit → loser_team=A" \
  "$(echo "$SUBMIT_RESP" | jq -r '.loser_team // "null"')" "A"

# ── Step 10: Verify intermediate states ──────────────────────────────────────
echo ""
echo "── Step 10: Verify intermediate states after score submission ──"

IGGY_AFTER_SUBMIT=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_IGGY" | jq -r '.mode // .play_tab.state // "null"')
ALICE_AFTER_SUBMIT=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
BOB_AFTER_SUBMIT=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_BOB" | jq -r '.mode // .play_tab.state // "null"')
CHARLIE_AFTER_SUBMIT=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_CHARLIE" | jq -r '.mode // .play_tab.state // "null"')

assert_eq "Iggy (submitter, Team B) → POST_MATCH_WAITING_OPPONENT" \
  "$IGGY_AFTER_SUBMIT" "POST_MATCH_WAITING_OPPONENT"
assert_eq "Alice (Team A, opposing) → POST_MATCH_CONFIRM_REQUIRED" \
  "$ALICE_AFTER_SUBMIT" "POST_MATCH_CONFIRM_REQUIRED"
assert_eq "Bob (Team A teammate of Alice) → POST_MATCH_CONFIRM_REQUIRED" \
  "$BOB_AFTER_SUBMIT" "POST_MATCH_CONFIRM_REQUIRED"
assert_eq "Charlie (Team B teammate of Iggy) → POST_MATCH_CONFIRM_REQUIRED" \
  "$CHARLIE_AFTER_SUBMIT" "POST_MATCH_CONFIRM_REQUIRED"

# ── Step 11: Confirm score (Alice, Team A, opposing team agrees winner_team=B) ─
echo ""
echo "── Step 11: Alice (Team A, opposing) confirms winner_team=B ──"

CONFIRM_RESP=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" \
  -H "Content-Type: application/json" \
  -d '{"winner_team":"B"}')

# ── Step 12: Verify match completed ─────────────────────────────────────────
echo ""
echo "── Step 12: Verify match is completed ──"

assert_eq "confirm → status=completed" \
  "$(echo "$CONFIRM_RESP" | jq -r '.status // "null"')" "completed"

# ── Step 13: Verify all 4 back at DISCOVERY ──────────────────────────────────
echo ""
echo "── Step 13: Verify all 4 participants return to DISCOVERY ──"

ALICE_FINAL=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
BOB_FINAL=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_BOB" | jq -r '.mode // .play_tab.state // "null"')
IGGY_FINAL=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_IGGY" | jq -r '.mode // .play_tab.state // "null"')
CHARLIE_FINAL=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_CHARLIE" | jq -r '.mode // .play_tab.state // "null"')

assert_eq "Alice after completion → DISCOVERY" "$ALICE_FINAL" "DISCOVERY"
assert_eq "Bob after completion → DISCOVERY" "$BOB_FINAL" "DISCOVERY"
assert_eq "Iggy after completion → DISCOVERY" "$IGGY_FINAL" "DISCOVERY"
assert_eq "Charlie after completion → DISCOVERY" "$CHARLIE_FINAL" "DISCOVERY"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke test smk-1-doubles-lifecycle: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
