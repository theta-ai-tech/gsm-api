#!/usr/bin/env bash
# Smoke tests for PR #286: feat: DBL-5 extend score logging for doubles (#169)
# Generated: 2026-05-01
# Usage: bash tests/smoke/pr-286.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/$PROJECT/databases/(default)/documents"

MATCH_ID="manual_dbl_5_pr286"
SINGLES_MATCH_ID="match_pending"

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

# ── Helpers ────────────────────────────────────────────────────────────────

assert_eq() {
  local name="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  ✓ $name"
    PASS=$((PASS+1))
  else
    echo "  ✗ $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    FAIL=$((FAIL+1))
  fi
}

firestore_delete() {
  local path="$1"
  curl -s -X DELETE "$FIRESTORE/$path" > /dev/null
}

firestore_put_user() {
  # Seed (or reset) a user doc with the playTab map the service needs to update.
  # The verify-score txn does dot-path updates on playTab.state/activeMatchId/
  # updatedAt; without a pre-existing doc Firestore returns 404 "no entity to
  # update" and the request 500s. Includes a tennis ranking so the singles
  # scoring path (used elsewhere in the legacy regression) does not blow up.
  local uid="$1"
  local name="$2"
  curl -s -X PATCH "$FIRESTORE/users/$uid" \
    -H "Content-Type: application/json" \
    -d "{
      \"fields\": {
        \"uid\": {\"stringValue\": \"$uid\"},
        \"name\": {\"stringValue\": \"$name\"},
        \"email\": {\"stringValue\": \"$uid@gsm.local\"},
        \"playTab\": {\"mapValue\": {\"fields\": {
          \"state\": {\"stringValue\": \"DISCOVERY\"},
          \"activeBroadcastId\": {\"nullValue\": null},
          \"activeOutgoingOfferId\": {\"nullValue\": null},
          \"activeMatchId\": {\"nullValue\": null},
          \"pendingIncomingOfferIds\": {\"arrayValue\": {\"values\": []}}
        }}},
        \"rankings\": {\"mapValue\": {\"fields\": {
          \"tennis\": {\"mapValue\": {\"fields\": {
            \"pts\": {\"integerValue\": \"1000\"},
            \"tier\": {\"stringValue\": \"AMATEUR\"}
          }}}
        }}}
      }
    }" > /dev/null
}

firestore_put_singles_match() {
  # Seed a scheduled singles tennis match between Alice and Iggy. The smoke's
  # singles regression (winner_team rejected on a singles match) needs the
  # match to exist in SCHEDULED status so the request gets past the
  # not-found check and reaches the doubles/singles guard.
  curl -s -X PATCH "$FIRESTORE/matches/$SINGLES_MATCH_ID" \
    -H "Content-Type: application/json" \
    -d '{
      "fields": {
        "sport": {"stringValue": "tennis"},
        "status": {"stringValue": "scheduled"},
        "matchType": {"stringValue": "singles"},
        "participantUids": {"arrayValue": {"values": [
          {"stringValue": "user_alice"},
          {"stringValue": "user_ignatios"}
        ]}},
        "participants": {"arrayValue": {"values": [
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_alice"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Alice"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_ignatios"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Ignatios"}
          }}}
        ]}},
        "resultSubmittedBy": {"arrayValue": {}},
        "resultByUser": {"mapValue": {}}
      }
    }' > /dev/null
}

seed_users() {
  firestore_put_user "user_alice"    "Alice Test"
  firestore_put_user "user_ignatios" "Ignatios Test"
  firestore_put_user "user_bob"      "Bob Test"
  firestore_put_user "user_charlie"  "Charlie Test"
}

firestore_put_match() {
  # Seed the doubles match document used across tests.
  curl -s -X PATCH "$FIRESTORE/matches/$MATCH_ID" \
    -H "Content-Type: application/json" \
    -d '{
      "fields": {
        "sport": {"stringValue": "tennis"},
        "status": {"stringValue": "scheduled"},
        "matchType": {"stringValue": "doubles"},
        "participantUids": {"arrayValue": {"values": [
          {"stringValue": "user_alice"},
          {"stringValue": "user_ignatios"},
          {"stringValue": "user_bob"},
          {"stringValue": "user_charlie"}
        ]}},
        "participants": {"arrayValue": {"values": [
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_alice"},
            "team": {"stringValue": "A"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Alice"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_ignatios"},
            "team": {"stringValue": "A"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Ignatios"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_bob"},
            "team": {"stringValue": "B"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Bob"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_charlie"},
            "team": {"stringValue": "B"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Charlie"}
          }}}
        ]}},
        "resultSubmittedBy": {"arrayValue": {}},
        "resultByUser": {"mapValue": {}}
      }
    }' > /dev/null
}

reset_match() {
  firestore_delete "matches/$MATCH_ID"
  firestore_put_match
  # Reset playTab on all 4 doubles participants so /me/state starts at DISCOVERY
  # before each scenario, otherwise a previous scenario's POST_MATCH_* state
  # leaks into subsequent assertions.
  seed_users
  sleep 0.2
}

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN_ALICE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
TOKEN_IGGY=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
TOKEN_BOB=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_bob -t 2>/dev/null)
TOKEN_CHARLIE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_charlie -t 2>/dev/null)

if [ -z "$TOKEN_ALICE" ] || [ -z "$TOKEN_IGGY" ] || [ -z "$TOKEN_BOB" ] || [ -z "$TOKEN_CHARLIE" ]; then
  echo "ERROR: Could not get auth tokens for all 4 seeded users. Is the auth emulator running and seeded?"
  exit 1
fi

# Self-seed Firestore. We do not rely on `make seed-emu` having been run —
# the smoke must be hermetic. We need:
#   - users/{uid} for all 4 doubles participants (the verify-score txn updates
#     playTab dot-paths, which 404 if the doc doesn't exist)
#   - matches/$SINGLES_MATCH_ID for the doubles-vs-singles validation guard
seed_users
firestore_put_singles_match

# ── Tests ───────────────────────────────────────────────────────────────────

echo "── Scenario 1: Doubles happy path (opposing-team confirmation) ──"
reset_match

# Step 1: Alice (team A) submits winner_team=A
RESP=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" -H "Content-Type: application/json" \
  -d '{"winner_team":"A","score":{"sets":[{"p1_games":6,"p2_games":3},{"p1_games":6,"p2_games":4}]}}')
assert_eq "Alice submits doubles result → status=pending_confirmation" \
  "$(echo "$RESP" | jq -r '.status // "null"')" "pending_confirmation"
assert_eq "Response carries winner_team=A" \
  "$(echo "$RESP" | jq -r '.winner_team // "null"')" "A"
assert_eq "Response carries loser_team=B" \
  "$(echo "$RESP" | jq -r '.loser_team // "null"')" "B"

# Step 2: Submitter playTab state
ALICE_MODE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Alice → POST_MATCH_WAITING_OPPONENT" "$ALICE_MODE" "POST_MATCH_WAITING_OPPONENT"

# Step 3: Other 3 participants
IGGY_MODE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_IGGY" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Ignatios (team A teammate) → POST_MATCH_CONFIRM_REQUIRED" "$IGGY_MODE" "POST_MATCH_CONFIRM_REQUIRED"
BOB_MODE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_BOB" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Bob (team B opponent) → POST_MATCH_CONFIRM_REQUIRED" "$BOB_MODE" "POST_MATCH_CONFIRM_REQUIRED"
CHARLIE_MODE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_CHARLIE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Charlie (team B opponent) → POST_MATCH_CONFIRM_REQUIRED" "$CHARLIE_MODE" "POST_MATCH_CONFIRM_REQUIRED"

# Step 4: Same-team confirmation rejected (409)
SAME_TEAM_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_IGGY" -H "Content-Type: application/json" \
  -d '{"winner_team":"A"}')
assert_eq "Same-team confirmation (Ignatios) → 409" "$SAME_TEAM_CODE" "409"

# Step 5: Opposing-team agreement completes the match
RESP2=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_BOB" -H "Content-Type: application/json" \
  -d '{"winner_team":"A"}')
assert_eq "Bob (opposing team) confirms → status=completed" \
  "$(echo "$RESP2" | jq -r '.status // "null"')" "completed"

# Step 6: All 4 → DISCOVERY
ALICE_AFTER=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Alice after completion → DISCOVERY" "$ALICE_AFTER" "DISCOVERY"
BOB_AFTER=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_BOB" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Bob after completion → DISCOVERY" "$BOB_AFTER" "DISCOVERY"
CHARLIE_AFTER=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_CHARLIE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Charlie after completion → DISCOVERY" "$CHARLIE_AFTER" "DISCOVERY"

echo ""
echo "── Scenario 2: Doubles dispute (opposing-team disagreement) ──"
reset_match

curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" -H "Content-Type: application/json" \
  -d '{"winner_team":"A"}' > /dev/null

DISP=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_BOB" -H "Content-Type: application/json" \
  -d '{"winner_team":"B"}')
assert_eq "Opposing-team disagreement → status=disputed" \
  "$(echo "$DISP" | jq -r '.status // "null"')" "disputed"

ALICE_DISP=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Alice in dispute → MATCH_DISPUTED" "$ALICE_DISP" "MATCH_DISPUTED"
CHARLIE_DISP=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_CHARLIE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Charlie in dispute → MATCH_DISPUTED" "$CHARLIE_DISP" "MATCH_DISPUTED"

echo ""
echo "── Scenario 3: Validation rejections ──"

# winner_team rejected on a singles match (409)
SINGLES_REJECT=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/matches/$SINGLES_MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_IGGY" -H "Content-Type: application/json" \
  -d '{"winner_team":"A"}')
assert_eq "winner_team on singles match → 409" "$SINGLES_REJECT" "409"

# Doubles submission missing winner_team (with no winner_uid either) → 422
reset_match
MISSING_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" -H "Content-Type: application/json" \
  -d '{}')
assert_eq "Missing winner_uid and winner_team → 422" "$MISSING_CODE" "422"

# winner_uid on a doubles match → 409
WUID_DOUBLES=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" -H "Content-Type: application/json" \
  -d '{"winner_uid":"user_alice"}')
assert_eq "winner_uid on doubles match → 409" "$WUID_DOUBLES" "409"

# Non-participant attempting verify-score → 403
TOKEN_OTHER=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_dan -t 2>/dev/null || echo "")
if [ -n "$TOKEN_OTHER" ]; then
  NONP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/matches/$MATCH_ID/verify-score" \
    -H "Authorization: Bearer $TOKEN_OTHER" -H "Content-Type: application/json" \
    -d '{"winner_team":"A"}')
  assert_eq "Non-participant → 403" "$NONP_CODE" "403"
else
  echo "  · skipped non-participant 403 check (user_dan not seeded)"
fi

# ── Teardown ────────────────────────────────────────────────────────────────
firestore_delete "matches/$MATCH_ID"
firestore_delete "matches/$SINGLES_MATCH_ID"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #286: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
