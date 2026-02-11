#!/usr/bin/env bash
# =============================================================================
# smoke_play.sh — Smoke test for Tab 1 PLAY API endpoints
#
# Tests integration scenarios end-to-end via curl, then reads directly from
# the Firestore emulator to verify state was written correctly.
#
# Prerequisites (start in separate terminals before running):
#   make emu-all            — Firestore + Auth emulators
#   make api-dev-emu-auth   — API server with emulator auth
#
# Usage:
#   ./scripts/smoke_play.sh
#
# Optional env overrides:
#   GSM_API_URL=http://127.0.0.1:8000
#   FIRESTORE_EMULATOR_HOST=127.0.0.1:8082
#   FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099
#   GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0
# =============================================================================
set -euo pipefail

# ---- Config ------------------------------------------------------------------
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
API_URL="${GSM_API_URL:-http://127.0.0.1:8000}"
FS_EMU="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
AUTH_EMU="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"

FS_BASE="http://${FS_EMU}/v1/projects/${PROJECT_ID}/databases/(default)/documents"
AUTH_BASE="http://${AUTH_EMU}/identitytoolkit.googleapis.com/v1"
FAKE_API_KEY="fake-api-key"

# Unique suffix so re-runs don't collide on user emails
RUN_ID=$(date +%s)

# ---- Colors ------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0

# ---- Assertion helpers -------------------------------------------------------
pass() { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)) || true; }
fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)) || true; }

section() {
  echo ""
  echo -e "${CYAN}━━━ $1 ━━━${NC}"
}

assert_eq() {
  local label="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "${label}: ${actual}"
  else
    fail "${label}: expected '${expected}', got '${actual}'"
  fi
}

assert_not_empty() {
  local label="$1" value="$2"
  if [[ -n "$value" && "$value" != "null" && "$value" != "" ]]; then
    pass "${label}"
  else
    fail "${label}: expected non-empty value, got '${value}'"
  fi
}

assert_http() {
  local label="$1" actual="$2" expected="$3"
  assert_eq "${label} (HTTP ${actual})" "$actual" "$expected"
}

# ---- HTTP helpers ------------------------------------------------------------

# Authenticated API call — returns response body
api() {
  local method="$1" path="$2" token="$3" body="${4:-}"
  if [[ -n "$body" ]]; then
    curl -s --max-time 10 -X "$method" "${API_URL}${path}" \
      -H "Authorization: Bearer ${token}" \
      -H "Content-Type: application/json" \
      -d "$body"
  else
    curl -s --max-time 10 -X "$method" "${API_URL}${path}" \
      -H "Authorization: Bearer ${token}"
  fi
}

# Authenticated API call — returns only HTTP status code
api_code() {
  local method="$1" path="$2" token="$3" body="${4:-}"
  if [[ -n "$body" ]]; then
    curl -s --max-time 10 -o /dev/null -w "%{http_code}" -X "$method" "${API_URL}${path}" \
      -H "Authorization: Bearer ${token}" \
      -H "Content-Type: application/json" \
      -d "$body"
  else
    curl -s --max-time 10 -o /dev/null -w "%{http_code}" -X "$method" "${API_URL}${path}" \
      -H "Authorization: Bearer ${token}"
  fi
}

# ---- Firestore REST helpers --------------------------------------------------

# Read a single field from a Firestore document (emulator REST API, no auth needed)
fs_field() {
  local collection="$1" doc_id="$2" jq_path="$3"
  curl -s --max-time 10 "${FS_BASE}/${collection}/${doc_id}" | jq -r "${jq_path} // \"null\""
}

# Read the full Firestore document as JSON
fs_doc() {
  local collection="$1" doc_id="$2"
  curl -s --max-time 10 "${FS_BASE}/${collection}/${doc_id}"
}

# Shorthand: read playTab.state for a user
user_state() {
  fs_field "users" "$1" '.fields.playTab.mapValue.fields.state.stringValue'
}

# Count items in a Firestore array field
fs_array_len() {
  local collection="$1" doc_id="$2" jq_path="$3"
  curl -s "${FS_BASE}/${collection}/${doc_id}" | \
    jq "${jq_path} | length // 0"
}

# Reset a user's playTab to DISCOVERY (direct Firestore write, bypasses API)
reset_user() {
  local uid="$1"
  local now; now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  curl -s --max-time 10 -X PATCH \
    "${FS_BASE}/users/${uid}?updateMask.fieldPaths=playTab" \
    -H "Content-Type: application/json" \
    -d @- > /dev/null <<EOF
{
  "fields": {
    "playTab": {
      "mapValue": {
        "fields": {
          "state":     {"stringValue": "DISCOVERY"},
          "updatedAt": {"timestampValue": "${now}"}
        }
      }
    }
  }
}
EOF
}

# Seed a user document in Firestore (creates or overwrites)
seed_user() {
  local uid="$1" name="$2" email="$3"
  local now; now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  curl -s --max-time 10 -X PATCH "${FS_BASE}/users/${uid}" \
    -H "Content-Type: application/json" \
    -d @- > /dev/null <<EOF
{
  "fields": {
    "name":  {"stringValue": "${name}"},
    "email": {"stringValue": "${email}"},
    "rankings": {
      "mapValue": {
        "fields": {
          "tennis": {
            "mapValue": {
              "fields": {
                "sport":         {"stringValue": "tennis"},
                "pts":           {"integerValue": "1200"},
                "globalRanking": {"integerValue": "42"}
              }
            }
          }
        }
      }
    },
    "playTab": {
      "mapValue": {
        "fields": {
          "state":     {"stringValue": "DISCOVERY"},
          "updatedAt": {"timestampValue": "${now}"}
        }
      }
    }
  }
}
EOF
}

# Delete a specific Firestore document
fs_delete() {
  local collection="$1" doc_id="$2"
  curl -s -X DELETE "${FS_BASE}/${collection}/${doc_id}" > /dev/null
}

# List and delete all documents in a collection (emulator only)
clear_collection() {
  local collection="$1"
  local names
  names=$(curl -s "${FS_BASE}/${collection}?pageSize=300" \
    | jq -r '.documents[]?.name // empty' 2>/dev/null || true)
  while IFS= read -r doc_name; do
    [[ -z "$doc_name" ]] && continue
    curl -s -X DELETE "http://${FS_EMU}/v1/${doc_name}" > /dev/null
  done <<< "$names"
}

# ---- Auth emulator helpers ---------------------------------------------------

# Sign up a new user in the Auth emulator and return the full JSON response
auth_signup() {
  local email="$1" password="${2:-smoke_pass_123}"
  curl -s --max-time 10 -X POST \
    "${AUTH_BASE}/accounts:signUp?key=${FAKE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${email}\",\"password\":\"${password}\",\"returnSecureToken\":true}" \
    || echo "{}"
}

# ---- Connectivity checks -----------------------------------------------------
check_connectivity() {
  section "Connectivity Checks"

  # API
  local api_code
  api_code=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/health" || echo "000")
  if [[ "$api_code" == "200" ]]; then
    pass "API reachable at ${API_URL}"
  else
    echo -e "${RED}✗ API not reachable at ${API_URL} (HTTP ${api_code})${NC}"
    echo "  → Start with: make api-dev-emu-auth"
    exit 1
  fi

  # Firestore emulator
  local fs_code
  fs_code=$(curl -s -o /dev/null -w "%{http_code}" \
    "http://${FS_EMU}/v1/projects/${PROJECT_ID}/databases/(default)/documents/smoke?pageSize=1" \
    2>/dev/null || echo "000")
  if [[ "$fs_code" != "000" ]]; then
    pass "Firestore emulator reachable at ${FS_EMU}"
  else
    echo -e "${RED}✗ Firestore emulator not reachable at ${FS_EMU}${NC}"
    echo "  → Start with: make emu-all"
    exit 1
  fi

  # Auth emulator — test the actual signUp endpoint, not just port availability
  local auth_probe auth_token
  auth_probe=$(curl -s --max-time 10 -X POST \
    "${AUTH_BASE}/accounts:signUp?key=${FAKE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"email":"probe@smoke.test","password":"probe_pass","returnSecureToken":true}' \
    2>/dev/null || echo "{}")
  auth_token=$(echo "$auth_probe" | jq -r '.idToken // empty' 2>/dev/null || true)
  if [[ -n "$auth_token" ]]; then
    pass "Auth emulator reachable at ${AUTH_EMU} (signUp endpoint OK)"
  else
    echo -e "${RED}✗ Auth emulator signUp endpoint not working at ${AUTH_EMU}${NC}"
    echo "  Raw response: ${auth_probe}"
    echo "  → Start with: make emu-all"
    exit 1
  fi

  # jq
  if command -v jq > /dev/null 2>&1; then
    pass "jq available ($(jq --version))"
  else
    echo -e "${RED}✗ jq not found — install with: brew install jq${NC}"
    exit 1
  fi
}

# ---- Test user setup ---------------------------------------------------------
ALICE_UID="" ALICE_TOKEN=""
BOB_UID=""   BOB_TOKEN=""
CHARLIE_UID="" CHARLIE_TOKEN=""

setup_users() {
  section "Setting Up Test Users"

  local alice_resp bob_resp charlie_resp

  echo "  Signing up Alice..."
  alice_resp=$(auth_signup "alice.smoke.${RUN_ID}@test.com")
  ALICE_UID=$(echo "$alice_resp"   | jq -r '.localId // empty')
  ALICE_TOKEN=$(echo "$alice_resp" | jq -r '.idToken // empty')
  if [[ -z "$ALICE_TOKEN" || "$ALICE_TOKEN" == "null" ]]; then
    echo -e "${RED}✗ Failed to obtain Alice's auth token.${NC}"
    echo "  Auth response: ${alice_resp}"
    exit 1
  fi

  echo "  Signing up Bob..."
  bob_resp=$(auth_signup "bob.smoke.${RUN_ID}@test.com")
  BOB_UID=$(echo "$bob_resp"   | jq -r '.localId // empty')
  BOB_TOKEN=$(echo "$bob_resp" | jq -r '.idToken // empty')
  if [[ -z "$BOB_TOKEN" || "$BOB_TOKEN" == "null" ]]; then
    echo -e "${RED}✗ Failed to obtain Bob's auth token.${NC}"
    echo "  Auth response: ${bob_resp}"
    exit 1
  fi

  echo "  Signing up Charlie..."
  charlie_resp=$(auth_signup "charlie.smoke.${RUN_ID}@test.com")
  CHARLIE_UID=$(echo "$charlie_resp"   | jq -r '.localId // empty')
  CHARLIE_TOKEN=$(echo "$charlie_resp" | jq -r '.idToken // empty')
  if [[ -z "$CHARLIE_TOKEN" || "$CHARLIE_TOKEN" == "null" ]]; then
    echo -e "${RED}✗ Failed to obtain Charlie's auth token.${NC}"
    echo "  Auth response: ${charlie_resp}"
    exit 1
  fi

  pass "Alice auth token obtained (uid: ${ALICE_UID})"
  pass "Bob auth token obtained (uid: ${BOB_UID})"
  pass "Charlie auth token obtained (uid: ${CHARLIE_UID})"

  seed_user "$ALICE_UID"   "Alice"   "alice.smoke.${RUN_ID}@test.com"
  seed_user "$BOB_UID"     "Bob"     "bob.smoke.${RUN_ID}@test.com"
  seed_user "$CHARLIE_UID" "Charlie" "charlie.smoke.${RUN_ID}@test.com"
  pass "User docs seeded in Firestore"
}

# ---- Scenario 1: Health ------------------------------------------------------
test_health() {
  section "Scenario 1 — Health Endpoint"

  local resp
  resp=$(curl -s "${API_URL}/health")
  assert_eq "status"  "$(echo "$resp" | jq -r '.status')"  "ok"
  assert_eq "service" "$(echo "$resp" | jq -r '.service')" "gsm-api"
  assert_eq "ok flag" "$(echo "$resp" | jq -r '.ok')"      "true"
}

# ---- Scenario 2: Broadcast flow ----------------------------------------------
test_broadcast_flow() {
  section "Scenario 2 — Broadcast: Create → Verify → Cancel → Verify"

  local expires_at
  expires_at=$(date -u -v+2H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
    || date -u -d "+2 hours" +"%Y-%m-%dT%H:%M:%SZ")

  # Create broadcast
  local create_resp broadcast_id
  create_resp=$(api POST /me/broadcast "$ALICE_TOKEN" \
    "{\"sport\":\"tennis\",\"availability\":\"today\",\"court_status\":\"have_court\",
      \"court_location\":\"Central Park\",\"expires_at\":\"${expires_at}\",
      \"location\":{\"area\":10001}}")
  broadcast_id=$(echo "$create_resp" | jq -r '.broadcast_id')

  assert_not_empty "POST /me/broadcast → broadcast_id"  "$broadcast_id"
  assert_eq        "Response sport"                     "$(echo "$create_resp" | jq -r '.sport')"   "tennis"
  assert_eq        "Response status"                    "$(echo "$create_resp" | jq -r '.status')"  "active"

  sleep 0.5

  # Firestore verification: user state
  assert_eq "Firestore: Alice → BROADCAST_ACTIVE" \
    "$(user_state "$ALICE_UID")" "BROADCAST_ACTIVE"
  assert_eq "Firestore: activeBroadcastId set" \
    "$(fs_field "users" "$ALICE_UID" '.fields.playTab.mapValue.fields.activeBroadcastId.stringValue')" \
    "$broadcast_id"

  # Firestore verification: broadcast doc
  assert_eq "Firestore: broadcast doc status=active" \
    "$(fs_field "broadcasts" "$broadcast_id" '.fields.status.stringValue')" "active"

  sleep 0.3

  # GET /me/state
  local state_resp
  state_resp=$(api GET /me/state "$ALICE_TOKEN")
  assert_eq "GET /me/state → BROADCAST_ACTIVE" \
    "$(echo "$state_resp" | jq -r '.mode')" "BROADCAST_ACTIVE"

  sleep 0.5

  # Cancel broadcast
  local cancel_code
  cancel_code=$(api_code DELETE /me/broadcast "$ALICE_TOKEN")
  assert_http "DELETE /me/broadcast" "$cancel_code" "204"

  sleep 0.5

  # Firestore verification after cancel
  assert_eq "Firestore: Alice → DISCOVERY after cancel" \
    "$(user_state "$ALICE_UID")" "DISCOVERY"
  assert_eq "Firestore: broadcast doc status=cancelled" \
    "$(fs_field "broadcasts" "$broadcast_id" '.fields.status.stringValue')" "cancelled"
}

# ---- Scenario 3: Direct challenge → accept -----------------------------------
test_direct_challenge_accept() {
  section "Scenario 3 — Direct Challenge: Send Offer → Accept → MATCH_SCHEDULED"

  local proposed_time
  proposed_time=$(date -u -v+3H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
    || date -u -d "+3 hours" +"%Y-%m-%dT%H:%M:%SZ")

  # Alice sends offer to Bob
  local offer_resp offer_id
  offer_resp=$(api POST /me/offers "$ALICE_TOKEN" \
    "{\"to_uid\":\"${BOB_UID}\",\"sport\":\"tennis\",
      \"proposed_time\":\"${proposed_time}\",
      \"court_location\":\"Central Park\",\"message\":\"Smoke test — let's play!\"}")
  offer_id=$(echo "$offer_resp" | jq -r '.offer_id')

  assert_not_empty "POST /me/offers → offer_id" "$offer_id"
  assert_eq        "Response offer status=pending" \
    "$(echo "$offer_resp" | jq -r '.status')" "pending"

  sleep 0.5

  # Firestore: state transitions
  assert_eq "Firestore: Alice → OUTGOING_OFFER_PENDING" \
    "$(user_state "$ALICE_UID")" "OUTGOING_OFFER_PENDING"
  assert_eq "Firestore: Bob → INCOMING_OFFER_PENDING" \
    "$(user_state "$BOB_UID")" "INCOMING_OFFER_PENDING"

  sleep 0.5

  # Bob accepts
  local accept_resp match_id
  accept_resp=$(api POST "/me/offers/${offer_id}/accept" "$BOB_TOKEN")
  match_id=$(echo "$accept_resp" | jq -r '.match_id')

  assert_eq        "Accept → status=accepted" \
    "$(echo "$accept_resp" | jq -r '.status')" "accepted"
  assert_not_empty "Accept → match_id returned" "$match_id"

  sleep 0.5

  # Firestore: both users MATCH_SCHEDULED with same match_id
  assert_eq "Firestore: Alice → MATCH_SCHEDULED" \
    "$(user_state "$ALICE_UID")" "MATCH_SCHEDULED"
  assert_eq "Firestore: Bob → MATCH_SCHEDULED" \
    "$(user_state "$BOB_UID")" "MATCH_SCHEDULED"
  assert_eq "Firestore: Alice.activeMatchId = ${match_id}" \
    "$(fs_field "users" "$ALICE_UID" '.fields.playTab.mapValue.fields.activeMatchId.stringValue')" \
    "$match_id"
  assert_eq "Firestore: Bob.activeMatchId = ${match_id}" \
    "$(fs_field "users" "$BOB_UID" '.fields.playTab.mapValue.fields.activeMatchId.stringValue')" \
    "$match_id"

  # Firestore: offer doc
  assert_eq "Firestore: offer doc status=accepted" \
    "$(fs_field "offers" "$offer_id" '.fields.status.stringValue')" "accepted"

  # Reset users to DISCOVERY for next scenarios
  reset_user "$ALICE_UID"
  reset_user "$BOB_UID"
}

# ---- Scenario 4: Direct challenge → decline ----------------------------------
test_direct_challenge_decline() {
  section "Scenario 4 — Direct Challenge: Send Offer → Decline → DISCOVERY"

  local proposed_time
  proposed_time=$(date -u -v+3H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
    || date -u -d "+3 hours" +"%Y-%m-%dT%H:%M:%SZ")

  local offer_resp offer_id
  offer_resp=$(api POST /me/offers "$ALICE_TOKEN" \
    "{\"to_uid\":\"${BOB_UID}\",\"sport\":\"tennis\",
      \"proposed_time\":\"${proposed_time}\"}")
  offer_id=$(echo "$offer_resp" | jq -r '.offer_id')

  assert_not_empty "POST /me/offers → offer_id" "$offer_id"

  sleep 0.5

  # Bob declines
  local decline_resp
  decline_resp=$(api POST "/me/offers/${offer_id}/decline" "$BOB_TOKEN")

  assert_eq "Decline → status=declined" \
    "$(echo "$decline_resp" | jq -r '.status')" "declined"

  sleep 0.5

  # Firestore: both back to DISCOVERY
  assert_eq "Firestore: Alice → DISCOVERY after decline" \
    "$(user_state "$ALICE_UID")" "DISCOVERY"
  assert_eq "Firestore: Bob → DISCOVERY after decline" \
    "$(user_state "$BOB_UID")" "DISCOVERY"
  assert_eq "Firestore: offer doc status=declined" \
    "$(fs_field "offers" "$offer_id" '.fields.status.stringValue')" "declined"
}

# ---- Scenario 5: Broadcast + offer queue → accept ----------------------------
test_broadcast_offer_queue() {
  section "Scenario 5 — Broadcast + Offer Queue: Accept One → Others Declined"

  local expires_at proposed_time
  expires_at=$(date -u -v+2H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
    || date -u -d "+2 hours" +"%Y-%m-%dT%H:%M:%SZ")
  proposed_time=$(date -u -v+3H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
    || date -u -d "+3 hours" +"%Y-%m-%dT%H:%M:%SZ")

  # Alice creates broadcast
  local bc_resp broadcast_id
  bc_resp=$(api POST /me/broadcast "$ALICE_TOKEN" \
    "{\"sport\":\"tennis\",\"availability\":\"today\",\"court_status\":\"have_court\",
      \"court_location\":\"Central Park\",\"expires_at\":\"${expires_at}\",
      \"location\":{\"area\":10001}}")
  broadcast_id=$(echo "$bc_resp" | jq -r '.broadcast_id')
  assert_not_empty "Alice creates broadcast" "$broadcast_id"

  sleep 0.5

  # Bob sends offer to Alice
  local bob_offer_id
  bob_offer_id=$(api POST /me/offers "$BOB_TOKEN" \
    "{\"to_uid\":\"${ALICE_UID}\",\"sport\":\"tennis\",
      \"proposed_time\":\"${proposed_time}\",\"message\":\"Bob's offer\"}" \
    | jq -r '.offer_id')
  assert_not_empty "Bob sends offer → offer_id" "$bob_offer_id"

  sleep 0.3

  # Charlie sends offer to Alice
  local charlie_offer_id
  charlie_offer_id=$(api POST /me/offers "$CHARLIE_TOKEN" \
    "{\"to_uid\":\"${ALICE_UID}\",\"sport\":\"tennis\",
      \"proposed_time\":\"${proposed_time}\",\"message\":\"Charlie's offer\"}" \
    | jq -r '.offer_id')
  assert_not_empty "Charlie sends offer → offer_id" "$charlie_offer_id"

  sleep 0.5

  # Firestore: Alice still BROADCAST_ACTIVE with 2 pending offers
  assert_eq "Firestore: Alice still BROADCAST_ACTIVE" \
    "$(user_state "$ALICE_UID")" "BROADCAST_ACTIVE"

  local pending_count
  pending_count=$(fs_array_len "users" "$ALICE_UID" \
    '.fields.playTab.mapValue.fields.pendingIncomingOfferIds.arrayValue.values')
  assert_eq "Firestore: Alice has 2 pending incoming offers" "$pending_count" "2"

  sleep 0.5

  # Alice accepts Bob's offer
  local accept_resp match_id
  accept_resp=$(api POST "/me/offers/${bob_offer_id}/accept" "$ALICE_TOKEN")
  match_id=$(echo "$accept_resp" | jq -r '.match_id')
  assert_not_empty "Alice accepts Bob's offer → match_id" "$match_id"

  sleep 0.5

  # Firestore: Alice and Bob MATCH_SCHEDULED
  assert_eq "Firestore: Alice → MATCH_SCHEDULED" \
    "$(user_state "$ALICE_UID")" "MATCH_SCHEDULED"
  assert_eq "Firestore: Bob → MATCH_SCHEDULED" \
    "$(user_state "$BOB_UID")" "MATCH_SCHEDULED"

  # Firestore: Charlie's offer declined
  assert_eq "Firestore: Charlie's offer declined" \
    "$(fs_field "offers" "$charlie_offer_id" '.fields.status.stringValue')" "declined"

  # Firestore: broadcast marked matched
  assert_eq "Firestore: broadcast status=matched" \
    "$(fs_field "broadcasts" "$broadcast_id" '.fields.status.stringValue')" "matched"

  # Firestore: pending list cleared
  local final_pending
  final_pending=$(fs_array_len "users" "$ALICE_UID" \
    '.fields.playTab.mapValue.fields.pendingIncomingOfferIds.arrayValue.values')
  assert_eq "Firestore: pending offers list cleared" "$final_pending" "0"

  # Reset for next scenario
  reset_user "$ALICE_UID"
  reset_user "$BOB_UID"
  reset_user "$CHARLIE_UID"
}

# ---- Scenario 6: Error cases -------------------------------------------------
test_error_cases() {
  section "Scenario 6 — Error Cases (4xx responses)"

  local now
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # cancel_broadcast with no active broadcast → 409
  assert_http "DELETE /me/broadcast (no broadcast) → 409" \
    "$(api_code DELETE /me/broadcast "$ALICE_TOKEN")" "409"

  sleep 0.3

  # accept non-existent offer → 404
  assert_http "POST /me/offers/nonexistent/accept → 404" \
    "$(api_code POST /me/offers/nonexistent_offer_id/accept "$ALICE_TOKEN")" "404"

  sleep 0.3

  # create broadcast with past expires_at → 409
  local past_time
  past_time=$(date -u -v-1H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
    || date -u -d "-1 hour" +"%Y-%m-%dT%H:%M:%SZ")
  assert_http "POST /me/broadcast (past expires_at) → 409" \
    "$(api_code POST /me/broadcast "$ALICE_TOKEN" \
      "{\"sport\":\"tennis\",\"availability\":\"today\",\"court_status\":\"have_court\",
        \"expires_at\":\"${past_time}\",\"location\":{\"area\":10001}}")" \
    "409"

  sleep 0.3

  # missing required field → 422
  assert_http "POST /me/broadcast (missing sport) → 422" \
    "$(api_code POST /me/broadcast "$ALICE_TOKEN" \
      "{\"availability\":\"today\",\"court_status\":\"have_court\",\"location\":{\"area\":10001}}")" \
    "422"

  sleep 0.3

  # Alice sends offer to Bob; Alice tries to accept own offer → 403
  local proposed_time offer_id
  proposed_time=$(date -u -v+3H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null \
    || date -u -d "+3 hours" +"%Y-%m-%dT%H:%M:%SZ")
  offer_id=$(api POST /me/offers "$ALICE_TOKEN" \
    "{\"to_uid\":\"${BOB_UID}\",\"sport\":\"tennis\",
      \"proposed_time\":\"${proposed_time}\"}" \
    | jq -r '.offer_id')

  sleep 0.3
  assert_http "POST /me/offers/{id}/accept (not recipient) → 403" \
    "$(api_code POST "/me/offers/${offer_id}/accept" "$ALICE_TOKEN")" "403"

  sleep 0.3

  # Alice cancels the offer (cleanup)
  api_code POST "/me/offers/${offer_id}/cancel" "$ALICE_TOKEN" > /dev/null || true
  reset_user "$ALICE_UID"
  reset_user "$BOB_UID"
}

# ---- Cleanup -----------------------------------------------------------------
cleanup() {
  section "Cleanup"

  # Delete test user docs
  fs_delete "users" "$ALICE_UID"
  fs_delete "users" "$BOB_UID"
  fs_delete "users" "$CHARLIE_UID"

  # Clear all broadcasts and offers created during the run
  clear_collection "broadcasts"
  clear_collection "offers"

  pass "Test data removed (users, broadcasts, offers)"
}

# ---- Summary -----------------------------------------------------------------
print_summary() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if [[ $FAIL -eq 0 ]]; then
    echo -e "  ${GREEN}All ${PASS} checks passed${NC}"
  else
    echo -e "  ${GREEN}${PASS} passed${NC}  ${RED}${FAIL} failed${NC}"
  fi
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  [[ $FAIL -eq 0 ]]
}

# ---- Main --------------------------------------------------------------------
main() {
  echo ""
  echo -e "${YELLOW}GSM API — Play Tab Smoke Test${NC}"
  echo "  API     : ${API_URL}"
  echo "  Firestore: ${FS_EMU}  |  Auth: ${AUTH_EMU}"
  echo "  Project : ${PROJECT_ID}  |  Run: ${RUN_ID}"

  check_connectivity
  setup_users
  test_health
  test_broadcast_flow
  test_direct_challenge_accept
  test_direct_challenge_decline
  test_broadcast_offer_queue
  test_error_cases
  cleanup
  print_summary
}

main
