#!/usr/bin/env bash
# Smoke tests for PR #315: feat: NTF-1 add notification intent contract for urgent play states
# Generated: 2026-05-30
# Usage: bash tests/smoke/pr-315.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8315}"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | grep "^worktree " | head -1 | sed 's/^worktree //')
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

assert_not_empty() {
  local name="$1" actual="$2"
  if [ -n "$actual" ] && [ "$actual" != "null" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (got empty/null)"
    ((FAIL++)) || true
  fi
}

firestore_list_subcollection() {
  # Returns the count of documents in a subcollection
  local path="$1"
  curl -s "$FIRESTORE/$path" | jq '.documents | length // 0'
}

firestore_get_first_field() {
  # Get a named field value from the first document in a subcollection
  local path="$1" field="$2"
  curl -s "$FIRESTORE/$path" | jq -r ".documents[0].fields.$field.stringValue // \"null\""
}

firestore_delete_doc() {
  local path="$1"
  curl -s -X DELETE "$FIRESTORE/$path" > /dev/null
}

firestore_delete_subcollection_docs() {
  # Delete all docs in a subcollection (reads IDs first, then deletes each)
  local path="$1"
  local doc_names
  doc_names=$(curl -s "$FIRESTORE/$path" | jq -r '.documents[]?.name // empty' 2>/dev/null || true)
  while IFS= read -r doc_name; do
    [ -z "$doc_name" ] && continue
    # doc_name is the full resource path; extract relative portion after /documents/
    local rel_path="${doc_name#*/documents/}"
    curl -s -X DELETE "$FIRESTORE/$rel_path" > /dev/null
  done <<< "$doc_names"
}

firestore_patch() {
  local path="$1" body="$2" mask="${3:-}"
  local url="$FIRESTORE/$path"
  [ -n "$mask" ] && url="$url?updateMask.fieldPaths=$mask"
  curl -s -X PATCH "$url" -H "Content-Type: application/json" -d "$body" > /dev/null
}

# ── Token acquisition ───────────────────────────────────────────────────────
echo "Acquiring tokens..."
ALICE_TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
BOB_TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_bob -t 2>/dev/null)

if [ -z "$ALICE_TOKEN" ] || [ -z "$BOB_TOKEN" ]; then
  echo "ERROR: Could not get auth tokens. Is the auth emulator running?"
  exit 1
fi

ALICE_UID="user_alice"
BOB_UID="user_bob"

# ── Pre-test cleanup ─────────────────────────────────────────────────────────
echo "Cleaning up any prior run state..."
firestore_delete_subcollection_docs "users/$ALICE_UID/notificationIntents"
firestore_delete_subcollection_docs "users/$BOB_UID/notificationIntents"
# Reset playTab to DISCOVERY for both users
firestore_patch "users/$ALICE_UID" \
  '{"fields":{"playTab":{"mapValue":{"fields":{"state":{"stringValue":"DISCOVERY"},"activeBroadcastId":{"nullValue":null},"activeOutgoingOfferId":{"nullValue":null},"pendingIncomingOfferIds":{"arrayValue":{"values":[]}},"activeMatchId":{"nullValue":null}}}}}}' \
  "playTab"
firestore_patch "users/$BOB_UID" \
  '{"fields":{"playTab":{"mapValue":{"fields":{"state":{"stringValue":"DISCOVERY"},"activeBroadcastId":{"nullValue":null},"activeOutgoingOfferId":{"nullValue":null},"pendingIncomingOfferIds":{"arrayValue":{"values":[]}},"activeMatchId":{"nullValue":null}}}}}}' \
  "playTab"

echo ""

# ── Test 1: incoming_offer intent ──────────────────────────────────────────
echo "Test 1: incoming_offer intent emitted when Bob sends offer to Alice"

# Alice creates a broadcast
BROADCAST_RESP=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "match_type": "singles",
    "broadcast_type": "find_opponent",
    "availability": "today",
    "court_status": "have_court",
    "court_location": "Athens",
    "expires_at": "2030-01-01T12:00:00Z",
    "location": {"area": 202, "radius_km": 10}
  }')

BROADCAST_ID=$(echo "$BROADCAST_RESP" | jq -r '.broadcast_id // empty')
assert_not_empty "Alice broadcast created" "$BROADCAST_ID"

# Bob sends offer to Alice
OFFER_RESP=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $BOB_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"$ALICE_UID\",
    \"sport\": \"tennis\",
    \"match_type\": \"singles\",
    \"proposed_time\": \"2030-01-02T10:00:00Z\",
    \"source_broadcast_id\": \"$BROADCAST_ID\"
  }")

OFFER_ID=$(echo "$OFFER_RESP" | jq -r '.offer_id // empty')
assert_not_empty "Bob offer sent" "$OFFER_ID"

# Check Alice has 1 notificationIntent of type incoming_offer
ALICE_INTENT_COUNT=$(firestore_list_subcollection "users/$ALICE_UID/notificationIntents")
assert_eq "Alice has 1 incoming_offer intent" "$ALICE_INTENT_COUNT" "1"

ALICE_INTENT_TYPE=$(firestore_get_first_field "users/$ALICE_UID/notificationIntents" "type")
assert_eq "Alice intent type is incoming_offer" "$ALICE_INTENT_TYPE" "incoming_offer"

ALICE_INTENT_TARGET=$(firestore_get_first_field "users/$ALICE_UID/notificationIntents" "targetUid")
assert_eq "Alice intent targetUid is alice" "$ALICE_INTENT_TARGET" "$ALICE_UID"

ALICE_INTENT_OFFER=$(firestore_get_first_field "users/$ALICE_UID/notificationIntents" "offerId")
assert_not_empty "Alice intent has offerId set" "$ALICE_INTENT_OFFER"

echo ""

# ── Test 2: match_scheduled intent ─────────────────────────────────────────
echo "Test 2: match_scheduled intent emitted when Alice accepts offer"

ACCEPT_RESP=$(curl -s -X POST "$API/me/offers/$OFFER_ID/accept" \
  -H "Authorization: Bearer $ALICE_TOKEN")

MATCH_ID=$(echo "$ACCEPT_RESP" | jq -r '.match_id // empty')
assert_not_empty "Alice accepted offer, match created" "$MATCH_ID"

# Alice should have a match_scheduled intent
# (note: Alice already had 1 incoming_offer intent, now should have 1 match_scheduled too)
ALICE_MATCH_INTENT_COUNT=$(curl -s "$FIRESTORE/users/$ALICE_UID/notificationIntents" | \
  jq '[.documents[]? | select(.fields.type.stringValue == "match_scheduled")] | length')
assert_eq "Alice has 1 match_scheduled intent" "$ALICE_MATCH_INTENT_COUNT" "1"

# Bob should also have a match_scheduled intent
BOB_INTENT_COUNT=$(firestore_list_subcollection "users/$BOB_UID/notificationIntents")
assert_eq "Bob has 1 intent after accept" "$BOB_INTENT_COUNT" "1"

BOB_INTENT_TYPE=$(firestore_get_first_field "users/$BOB_UID/notificationIntents" "type")
assert_eq "Bob intent type is match_scheduled" "$BOB_INTENT_TYPE" "match_scheduled"

BOB_INTENT_MATCH=$(firestore_get_first_field "users/$BOB_UID/notificationIntents" "matchId")
assert_not_empty "Bob intent has matchId set" "$BOB_INTENT_MATCH"

echo ""

# ── Test 3: score_confirm_required intent ──────────────────────────────────
echo "Test 3: score_confirm_required intent emitted when Alice submits score"

SCORE_RESP=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"winner_uid\": \"$ALICE_UID\",
    \"score\": {\"sets\": [{\"p1_games\": 6, \"p2_games\": 4}]}
  }")

SCORE_STATUS=$(echo "$SCORE_RESP" | jq -r '.status // empty')
assert_eq "Score submission returns pending_confirmation" "$SCORE_STATUS" "pending_confirmation"

# Bob should now have a score_confirm_required intent (in addition to match_scheduled)
BOB_CONFIRM_INTENT_COUNT=$(curl -s "$FIRESTORE/users/$BOB_UID/notificationIntents" | \
  jq '[.documents[]? | select(.fields.type.stringValue == "score_confirm_required")] | length')
assert_eq "Bob has 1 score_confirm_required intent" "$BOB_CONFIRM_INTENT_COUNT" "1"

BOB_CONFIRM_MATCH_ID=$(curl -s "$FIRESTORE/users/$BOB_UID/notificationIntents" | \
  jq -r '[.documents[]? | select(.fields.type.stringValue == "score_confirm_required")][0].fields.matchId.stringValue // "null"')
assert_eq "Bob score_confirm intent has correct matchId" "$BOB_CONFIRM_MATCH_ID" "$MATCH_ID"

# Alice (submitter) should NOT have a score_confirm_required intent
ALICE_CONFIRM_INTENT_COUNT=$(curl -s "$FIRESTORE/users/$ALICE_UID/notificationIntents" | \
  jq '[.documents[]? | select(.fields.type.stringValue == "score_confirm_required")] | length')
assert_eq "Alice (submitter) has no score_confirm_required intent" "$ALICE_CONFIRM_INTENT_COUNT" "0"

echo ""

# ── Teardown ─────────────────────────────────────────────────────────────────
echo "Teardown: resetting state..."
# Delete notificationIntent documents
firestore_delete_subcollection_docs "users/$ALICE_UID/notificationIntents"
firestore_delete_subcollection_docs "users/$BOB_UID/notificationIntents"
# Delete match and offer
[ -n "${MATCH_ID:-}" ] && firestore_delete_doc "matches/$MATCH_ID" || true
[ -n "${OFFER_ID:-}" ] && firestore_delete_doc "offers/$OFFER_ID" || true
[ -n "${BROADCAST_ID:-}" ] && firestore_delete_doc "broadcasts/$BROADCAST_ID" || true
# Reset playTab to DISCOVERY
firestore_patch "users/$ALICE_UID" \
  '{"fields":{"playTab":{"mapValue":{"fields":{"state":{"stringValue":"DISCOVERY"},"activeBroadcastId":{"nullValue":null},"activeOutgoingOfferId":{"nullValue":null},"pendingIncomingOfferIds":{"arrayValue":{"values":[]}},"activeMatchId":{"nullValue":null}}}}}}' \
  "playTab"
firestore_patch "users/$BOB_UID" \
  '{"fields":{"playTab":{"mapValue":{"fields":{"state":{"stringValue":"DISCOVERY"},"activeBroadcastId":{"nullValue":null},"activeOutgoingOfferId":{"nullValue":null},"pendingIncomingOfferIds":{"arrayValue":{"values":[]}},"activeMatchId":{"nullValue":null}}}}}}' \
  "playTab"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #315: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
