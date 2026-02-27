#!/usr/bin/env bash
# =============================================================================
# smoke_improve.sh — Smoke test for Tab 2 IMPROVE API endpoints
#
# End-to-end curl smoke suite for:
# - /health
# - /me/journal (POST/GET/PATCH/list)
# - /me/stats
# - /me/north-star
# plus Firestore emulator direct verification and cleanup.
#
# Prerequisites (start in separate terminals before running):
#   make emu-all            — Firestore + Auth emulators
#   make api-dev-emu-auth   — API server with emulator auth
#
# Usage:
#   ./scripts/smoke_improve.sh
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

# Cross-user ownership checks should return forbidden.
EXPECT_CROSS_USER_PATCH="${EXPECT_CROSS_USER_PATCH:-403}"
EXPECT_CROSS_USER_GET="${EXPECT_CROSS_USER_GET:-403}"

RUN_ID=$(date +%s)

# ---- Colors ------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0

# ---- Globals -----------------------------------------------------------------
SMOKE_UID_A=""
SMOKE_UID_B=""
SMOKE_TOKEN_A=""
SMOKE_TOKEN_B=""

ENTRY_ID_MATCH=""
ENTRY_ID_TRAINING=""
MATCH_REF_ID="smoke_match_${RUN_ID}"

GOAL_TEXT="Win 10 matches this month"

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

assert_http() {
  local label="$1" actual="$2" expected="$3"
  assert_eq "${label} (HTTP ${actual})" "$actual" "$expected"
}

assert_not_empty() {
  local label="$1" value="$2"
  if [[ -n "$value" && "$value" != "null" ]]; then
    pass "${label}"
  else
    fail "${label}: expected non-empty value, got '${value}'"
  fi
}

# ---- HTTP helpers ------------------------------------------------------------
HTTP_CODE=""
RESP_BODY=""

api_call() {
  local method="$1" path="$2" token="${3:-}" body="${4:-}"
  local tmp
  tmp=$(mktemp)

  local -a cmd
  cmd=(curl -s --max-time 15 -o "$tmp" -w "%{http_code}" -X "$method" "${API_URL}${path}")

  if [[ -n "$token" ]]; then
    cmd+=(-H "Authorization: Bearer ${token}")
  fi
  if [[ -n "$body" ]]; then
    cmd+=(-H "Content-Type: application/json" -d "$body")
  fi

  HTTP_CODE="$("${cmd[@]}")"
  RESP_BODY="$(cat "$tmp")"
  rm -f "$tmp"
}

# ---- Firestore emulator helpers ---------------------------------------------
fs_get_rel() {
  local rel_path="$1"
  curl -s --max-time 10 "${FS_BASE}/${rel_path}"
}

fs_field_rel() {
  local rel_path="$1" jq_path="$2"
  fs_get_rel "$rel_path" | jq -r "${jq_path} // \"null\""
}

fs_list_doc_names_rel() {
  local rel_path="$1"
  curl -s --max-time 10 "${FS_BASE}/${rel_path}?pageSize=300" \
    | jq -r '.documents[]?.name // empty' 2>/dev/null || true
}

fs_delete_rel() {
  local rel_path="$1"
  curl -s --max-time 10 -X DELETE "${FS_BASE}/${rel_path}" > /dev/null || true
}

fs_delete_by_name() {
  local full_name="$1"
  curl -s --max-time 10 -X DELETE "http://${FS_EMU}/v1/${full_name}" > /dev/null || true
}

seed_user_doc() {
  local uid="$1" name="$2" email="$3"
  curl -s --max-time 10 -X PATCH "${FS_BASE}/users/${uid}" \
    -H "Content-Type: application/json" \
    -d @- > /dev/null <<EOF
{
  "fields": {
    "uid":   {"stringValue": "${uid}"},
    "name":  {"stringValue": "${name}"},
    "email": {"stringValue": "${email}"},
    "rankings": {
      "mapValue": {
        "fields": {
          "tennis": {
            "mapValue": {
              "fields": {
                "sport": {"stringValue": "tennis"},
                "pts": {"integerValue": "1200"},
                "globalRanking": {"integerValue": "42"}
              }
            }
          }
        }
      }
    }
  }
}
EOF
}

# ---- Auth emulator helpers ---------------------------------------------------
auth_signup() {
  local email="$1" password="${2:-smoke_pass_123}"
  curl -s --max-time 10 -X POST \
    "${AUTH_BASE}/accounts:signUp?key=${FAKE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${email}\",\"password\":\"${password}\",\"returnSecureToken\":true}" \
    || echo "{}"
}

# ---- Connectivity ------------------------------------------------------------
check_connectivity() {
  section "Connectivity Checks"

  local api_code
  api_code=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/health" || echo "000")
  if [[ "$api_code" == "200" ]]; then
    pass "API reachable at ${API_URL}"
  else
    echo -e "${RED}✗ API not reachable at ${API_URL} (HTTP ${api_code})${NC}"
    echo "  → Start with: make api-dev-emu-auth"
    exit 1
  fi

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

  local auth_probe auth_token
  local auth_error_message
  auth_probe=$(curl -s --max-time 10 -X POST \
    "${AUTH_BASE}/accounts:signUp?key=${FAKE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"email":"probe.improve@test.com","password":"probe_pass","returnSecureToken":true}' \
    2>/dev/null || echo "{}")
  auth_token=$(echo "$auth_probe" | jq -r '.idToken // empty' 2>/dev/null || true)
  auth_error_message=$(echo "$auth_probe" | jq -r '.error.message // empty' 2>/dev/null || true)
  if [[ -n "$auth_token" || "$auth_error_message" == "EMAIL_EXISTS" ]]; then
    pass "Auth emulator reachable at ${AUTH_EMU} (signUp endpoint OK)"
  else
    echo -e "${RED}✗ Auth emulator signUp endpoint not working at ${AUTH_EMU}${NC}"
    echo "  Raw response: ${auth_probe}"
    echo "  → Start with: make emu-all"
    exit 1
  fi

  if command -v jq > /dev/null 2>&1; then
    pass "jq available ($(jq --version))"
  else
    echo -e "${RED}✗ jq not found — install with: brew install jq${NC}"
    exit 1
  fi
}

setup_users() {
  section "Setting Up Test Users"

  local resp_a resp_b
  local email_a="improve.alice.${RUN_ID}@test.com"
  local email_b="improve.bob.${RUN_ID}@test.com"

  resp_a=$(auth_signup "$email_a")
  resp_b=$(auth_signup "$email_b")

  SMOKE_UID_A=$(echo "$resp_a" | jq -r '.localId // empty')
  SMOKE_TOKEN_A=$(echo "$resp_a" | jq -r '.idToken // empty')
  SMOKE_UID_B=$(echo "$resp_b" | jq -r '.localId // empty')
  SMOKE_TOKEN_B=$(echo "$resp_b" | jq -r '.idToken // empty')

  assert_not_empty "Alice uid from auth emulator" "$SMOKE_UID_A"
  assert_not_empty "Alice token from auth emulator" "$SMOKE_TOKEN_A"
  assert_not_empty "Bob uid from auth emulator" "$SMOKE_UID_B"
  assert_not_empty "Bob token from auth emulator" "$SMOKE_TOKEN_B"

  seed_user_doc "$SMOKE_UID_A" "Improve Alice" "$email_a"
  seed_user_doc "$SMOKE_UID_B" "Improve Bob" "$email_b"
  pass "Seeded Firestore user docs for smoke users"
}

# ---- Scenario 1 --------------------------------------------------------------
test_health() {
  section "Scenario 1 — Health check"
  api_call GET "/health"
  assert_http "GET /health" "$HTTP_CODE" "200"
  assert_eq "health.status" "$(echo "$RESP_BODY" | jq -r '.status // empty')" "ok"
}

# ---- Scenario 2 --------------------------------------------------------------
test_create_match_journal_entry() {
  section "Scenario 2 — Create match journal entry"

  local payload
  payload=$(jq -nc \
    --arg title "Smoke match entry ${RUN_ID}" \
    --arg body "End-to-end match journal smoke test." \
    --arg match_id "$MATCH_REF_ID" \
    '{
      entry_type: "match",
      title: $title,
      body: $body,
      sport: "tennis",
      match_id: $match_id,
      tags: ["smoke","match"]
    }')

  api_call POST "/me/journal" "$SMOKE_TOKEN_A" "$payload"
  assert_http "POST /me/journal (match)" "$HTTP_CODE" "201"

  ENTRY_ID_MATCH=$(echo "$RESP_BODY" | jq -r '.entry_id // empty')
  assert_not_empty "Match entry_id returned" "$ENTRY_ID_MATCH"
}

# ---- Scenario 3 --------------------------------------------------------------
test_create_training_journal_entry() {
  section "Scenario 3 — Create training journal entry"

  local payload
  payload=$(jq -nc \
    --arg title "Smoke training entry ${RUN_ID}" \
    '{
      entry_type: "training",
      title: $title,
      body: "Footwork and serve drills",
      sport: "tennis",
      duration_minutes: 45,
      training_focus: ["serve","footwork"],
      tags: ["smoke","training"]
    }')

  api_call POST "/me/journal" "$SMOKE_TOKEN_A" "$payload"
  assert_http "POST /me/journal (training)" "$HTTP_CODE" "201"

  ENTRY_ID_TRAINING=$(echo "$RESP_BODY" | jq -r '.entry_id // empty')
  assert_not_empty "Training entry_id returned" "$ENTRY_ID_TRAINING"
}

# ---- Scenario 4 --------------------------------------------------------------
test_list_entries() {
  section "Scenario 4 — List journal entries"

  api_call GET "/me/journal?limit=20" "$SMOKE_TOKEN_A"
  assert_http "GET /me/journal" "$HTTP_CODE" "200"

  local count has_match has_training
  count=$(echo "$RESP_BODY" | jq -r '.entries | length')
  has_match=$(echo "$RESP_BODY" | jq -r --arg id "$ENTRY_ID_MATCH" '[.entries[].entry_id] | index($id) != null')
  has_training=$(echo "$RESP_BODY" | jq -r --arg id "$ENTRY_ID_TRAINING" '[.entries[].entry_id] | index($id) != null')

  if [[ "$count" -ge 2 ]]; then
    pass "List returned at least two entries (${count})"
  else
    fail "List expected at least two entries, got ${count}"
  fi
  assert_eq "List contains match entry" "$has_match" "true"
  assert_eq "List contains training entry" "$has_training" "true"
}

# ---- Scenario 5 --------------------------------------------------------------
test_get_single_entry() {
  section "Scenario 5 — Get single journal entry"

  api_call GET "/me/journal/${ENTRY_ID_MATCH}" "$SMOKE_TOKEN_A"
  assert_http "GET /me/journal/{entry_id}" "$HTTP_CODE" "200"
  assert_eq "single entry_id matches" \
    "$(echo "$RESP_BODY" | jq -r '.entry_id // empty')" "$ENTRY_ID_MATCH"
}

# ---- Scenario 6 --------------------------------------------------------------
test_update_reflection() {
  section "Scenario 6 — Update journal entry reflection"

  local payload
  payload=$(jq -nc '{
    reflection: {
      went_well: ["first_serve","net_play"],
      went_wrong: ["double_faults"],
      opponent_weak: ["backhand"],
      opponent_strong: ["serve"]
    },
    tags: ["smoke","updated"],
    body: "Updated reflection body"
  }')

  api_call PATCH "/me/journal/${ENTRY_ID_MATCH}" "$SMOKE_TOKEN_A" "$payload"
  assert_http "PATCH /me/journal/{entry_id}" "$HTTP_CODE" "200"
  assert_eq "update response.updated" "$(echo "$RESP_BODY" | jq -r '.updated // empty')" "true"
}

# ---- Scenario 7 --------------------------------------------------------------
test_get_stats() {
  section "Scenario 7 — Get dashboard stats"

  api_call GET "/me/stats" "$SMOKE_TOKEN_A"
  assert_http "GET /me/stats" "$HTTP_CODE" "200"
  assert_eq "stats.uid matches caller" \
    "$(echo "$RESP_BODY" | jq -r '.uid // empty')" "$SMOKE_UID_A"
}

# ---- Scenario 8 --------------------------------------------------------------
test_set_north_star() {
  section "Scenario 8 — Set north star goal"

  local payload
  payload=$(jq -nc --arg goal "$GOAL_TEXT" '{goal_text: $goal}')

  api_call PUT "/me/north-star" "$SMOKE_TOKEN_A" "$payload"
  assert_http "PUT /me/north-star" "$HTTP_CODE" "200"
  assert_eq "north-star goal_text echoed back" \
    "$(echo "$RESP_BODY" | jq -r '.goal_text // empty')" "$GOAL_TEXT"
}

# ---- Scenario 9 --------------------------------------------------------------
test_firestore_verification() {
  section "Scenario 9 — Verify Firestore docs via emulator REST API"

  assert_eq "match doc entryType=match" \
    "$(fs_field_rel "users/${SMOKE_UID_A}/journalEntries/${ENTRY_ID_MATCH}" '.fields.entryType.stringValue')" \
    "match"
  assert_eq "match doc matchId link present" \
    "$(fs_field_rel "users/${SMOKE_UID_A}/journalEntries/${ENTRY_ID_MATCH}" '.fields.matchId.stringValue')" \
    "$MATCH_REF_ID"

  assert_eq "training doc entryType=training" \
    "$(fs_field_rel "users/${SMOKE_UID_A}/journalEntries/${ENTRY_ID_TRAINING}" '.fields.entryType.stringValue')" \
    "training"
  assert_eq "training doc durationMinutes=45" \
    "$(fs_field_rel "users/${SMOKE_UID_A}/journalEntries/${ENTRY_ID_TRAINING}" '.fields.durationMinutes.integerValue')" \
    "45"

  assert_eq "match reflection.wentWell[0]=first_serve" \
    "$(fs_field_rel "users/${SMOKE_UID_A}/journalEntries/${ENTRY_ID_MATCH}" '.fields.reflection.mapValue.fields.wentWell.arrayValue.values[0].stringValue')" \
    "first_serve"

  local recent_count
  recent_count=$(fs_get_rel "users/${SMOKE_UID_A}" \
    | jq -r '.fields.journalRecent.arrayValue.values | length // 0')
  if [[ "$recent_count" -ge 2 ]]; then
    pass "users/{uid}.journalRecent has at least two summaries (${recent_count})"
  else
    fail "users/{uid}.journalRecent expected at least two summaries, got ${recent_count}"
  fi

  assert_eq "users/{uid}.northStarGoal.goalText stored" \
    "$(fs_field_rel "users/${SMOKE_UID_A}" '.fields.northStarGoal.mapValue.fields.goalText.stringValue')" \
    "$GOAL_TEXT"
}

# ---- Scenario 10 -------------------------------------------------------------
test_error_cases() {
  section "Scenario 10 — Error cases"

  # 401: no Authorization header
  api_call GET "/me/stats"
  assert_http "GET /me/stats without Authorization" "$HTTP_CODE" "401"

  # 401: invalid token
  api_call GET "/me/stats" "this.is.an.invalid.token"
  assert_http "GET /me/stats with invalid token" "$HTTP_CODE" "401"

  # 403: PATCH with another user's entry_id (requested expectation)
  local patch_payload
  patch_payload=$(jq -nc '{tags:["cross-user"]}')
  api_call PATCH "/me/journal/${ENTRY_ID_MATCH}" "$SMOKE_TOKEN_B" "$patch_payload"
  assert_http "PATCH /me/journal/{id} with another user's entry_id" \
    "$HTTP_CODE" "$EXPECT_CROSS_USER_PATCH"

  # 403: GET with another user's entry_id (requested expectation)
  api_call GET "/me/journal/${ENTRY_ID_MATCH}" "$SMOKE_TOKEN_B"
  assert_http "GET /me/journal/{id} with another user's entry_id" \
    "$HTTP_CODE" "$EXPECT_CROSS_USER_GET"

  # 404: GET non-existent entry
  api_call GET "/me/journal/nonexistent_entry_id_${RUN_ID}" "$SMOKE_TOKEN_A"
  assert_http "GET /me/journal/{id} non-existent" "$HTTP_CODE" "404"

  # 404: PATCH non-existent entry
  api_call PATCH "/me/journal/nonexistent_entry_id_${RUN_ID}" "$SMOKE_TOKEN_A" "$patch_payload"
  assert_http "PATCH /me/journal/{id} non-existent" "$HTTP_CODE" "404"

  # 422: missing entry_type
  local payload_missing_type
  payload_missing_type=$(jq -nc '{title:"Missing type"}')
  api_call POST "/me/journal" "$SMOKE_TOKEN_A" "$payload_missing_type"
  assert_http "POST /me/journal missing entry_type" "$HTTP_CODE" "422"

  # 422: invalid enum entry_type
  local payload_invalid_enum
  payload_invalid_enum=$(jq -nc '{entry_type:"not_a_real_type",title:"Bad enum"}')
  api_call POST "/me/journal" "$SMOKE_TOKEN_A" "$payload_invalid_enum"
  assert_http "POST /me/journal invalid entry_type enum" "$HTTP_CODE" "422"

  # 422: tags count > 20
  local tags_over payload_tags_over
  tags_over=$(jq -nc '[range(0;21) | "tag" + (tostring)]')
  payload_tags_over=$(jq -nc --argjson tags "$tags_over" \
    '{entry_type:"match", title:"Too many tags", tags:$tags}')
  api_call POST "/me/journal" "$SMOKE_TOKEN_A" "$payload_tags_over"
  assert_http "POST /me/journal tags count > 20" "$HTTP_CODE" "422"

  # 422: north-star goal_text > 500 chars
  local long_goal payload_long_goal
  long_goal=$(printf 'x%.0s' $(seq 1 501))
  payload_long_goal=$(jq -nc --arg goal "$long_goal" '{goal_text:$goal}')
  api_call PUT "/me/north-star" "$SMOKE_TOKEN_A" "$payload_long_goal"
  assert_http "PUT /me/north-star goal_text > 500 chars" "$HTTP_CODE" "422"
}

# ---- Scenario 11 -------------------------------------------------------------
cleanup() {
  section "Scenario 11 — Cleanup"

  local uid
  for uid in "$SMOKE_UID_A" "$SMOKE_UID_B"; do
    [[ -z "$uid" ]] && continue

    # Delete all journalEntry docs created during the run (or any leftovers).
    local names
    names=$(fs_list_doc_names_rel "users/${uid}/journalEntries")
    while IFS= read -r full_name; do
      [[ -z "$full_name" ]] && continue
      fs_delete_by_name "$full_name"
    done <<< "$names"

    # Delete seeded user doc.
    fs_delete_rel "users/${uid}"
  done

  # Verify cleanup (re-run safety): user docs gone and subcollections empty.
  for uid in "$SMOKE_UID_A" "$SMOKE_UID_B"; do
    [[ -z "$uid" ]] && continue
    local user_code remaining_entries
    user_code=$(curl -s -o /dev/null -w "%{http_code}" "${FS_BASE}/users/${uid}" || echo "000")
    assert_eq "Cleanup: users/${uid} deleted" "$user_code" "404"

    remaining_entries=$(fs_get_rel "users/${uid}/journalEntries?pageSize=20" \
      | jq -r '.documents | length // 0')
    assert_eq "Cleanup: users/${uid}/journalEntries empty" "$remaining_entries" "0"
  done
}

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

main() {
  echo ""
  echo -e "${YELLOW}GSM API — Improve Tab Smoke Test${NC}"
  echo "  API      : ${API_URL}"
  echo "  Firestore: ${FS_EMU}  |  Auth: ${AUTH_EMU}"
  echo "  Project  : ${PROJECT_ID}  |  Run: ${RUN_ID}"
  echo "  Cross-user expected codes: PATCH=${EXPECT_CROSS_USER_PATCH}, GET=${EXPECT_CROSS_USER_GET}"

  check_connectivity
  setup_users

  test_health
  test_create_match_journal_entry
  test_create_training_journal_entry
  test_list_entries
  test_get_single_entry
  test_update_reflection
  test_get_stats
  test_set_north_star
  test_firestore_verification
  test_error_cases
  cleanup

  print_summary
}

main
