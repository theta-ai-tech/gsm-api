#!/usr/bin/env bash
# Smoke tests for PR #318: OBS-3 emit telemetry events for match completion and score confirmation
# Generated: 2026-05-31
# Usage: API_BASE_URL=http://127.0.0.1:8318 bash tests/smoke/pr-318.sh
#
# Requires: make emu-all + make api-dev-emu-auth running (separate terminals).
# Verifies that match_scheduled, score_submitted, score_confirmed, and match_disputed
# telemetry events are emitted to the API log during a full play cycle.
#
# Because events go to stdout (Cloud Logging in prod), this script runs the API
# in a subprocess, captures its log, and greps for the expected event JSON lines.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8318}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/$PROJECT/databases/(default)/documents"
LOG_FILE="/tmp/gsm-api-pr-318-smoke.log"
API_PID=""

# ── Venv resolution ──────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found. Run 'make venv && make install' in the main checkout."
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

assert_log_contains() {
  local name="$1" pattern="$2"
  if grep -q "$pattern" "$LOG_FILE" 2>/dev/null; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    pattern not found in API log: $pattern"
    ((FAIL++)) || true
  fi
}

reset_playtab() {
  for uid in user_ignatios user_alice; do
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

MATCH_ID=""

cleanup() {
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $IGGY" "$API/me/broadcast" 2>/dev/null || true
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $ALICE" "$API/me/broadcast" 2>/dev/null || true
  if [ -n "$MATCH_ID" ]; then
    curl -s -X DELETE "$FIRESTORE/matches/$MATCH_ID" > /dev/null 2>&1 || true
    MATCH_ID=""
  fi
  reset_playtab
}

stop_api() {
  if [ -n "$API_PID" ]; then
    kill "$API_PID" 2>/dev/null || true
    API_PID=""
  fi
}

# ── Start API (captures log for event assertions) ────────────────────────────
API_PORT="${API_PORT:-8318}"

# Check if the user has pre-started an API at this URL
if curl -fsS "$API/health" >/dev/null 2>&1; then
  echo "Using pre-started API at $API (log capture for event checks disabled)"
  echo "NOTE: telemetry event checks will be skipped — start API via this script for full coverage"
  LOG_CAPTURE=false
else
  LOG_CAPTURE=true
  (
    cd "$REPO_ROOT"
    . "$VENV_DIR/bin/activate"
    export FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
    export FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
    export GOOGLE_CLOUD_PROJECT="$PROJECT"
    export FIREBASE_PROJECT_ID="$PROJECT"
    uvicorn app.main:app --port "$API_PORT" --app-dir api
  ) >"$LOG_FILE" 2>&1 &
  API_PID=$!

  echo "Starting API (pid $API_PID) on port $API_PORT..."
  for _ in $(seq 1 30); do
    if curl -fsS "$API/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -fsS "$API/health" >/dev/null 2>&1; then
    echo "ABORT: API did not start. Check $LOG_FILE"
    stop_api
    exit 1
  fi
  echo "API healthy."
fi

trap 'cleanup; stop_api' EXIT

# ── Seed ─────────────────────────────────────────────────────────────────────
echo "Seeding Firestore..."
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}" \
GOOGLE_CLOUD_PROJECT="$PROJECT" \
  . "$VENV_DIR/bin/activate" && \
  python3 -m tools.seed_firestore 2>/dev/null || true

# ── Token acquisition ─────────────────────────────────────────────────────────
IGGY=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
ALICE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
if [ -z "$IGGY" ] || [ -z "$ALICE" ]; then
  echo "ERROR: Could not get auth tokens. Is the auth emulator running?"
  stop_api
  exit 1
fi

cleanup

# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Section 1: match_scheduled + score_submitted + score_confirmed (singles) ─"
# ═══════════════════════════════════════════════════════════════════════════════

# Alice creates broadcast
BROADCAST=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "availability": "today",
    "court_status": "have_court",
    "court_location": "Court A",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
BROADCAST_ID=$(echo "$BROADCAST" | jq -r '.broadcast_id // .id // empty')
assert_eq "Alice creates broadcast" "$([ -n "$BROADCAST_ID" ] && echo true || echo false)" "true"

# Iggy sends offer to Alice
OFFER=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"user_alice\",
    \"sport\": \"tennis\",
    \"proposed_time\": \"2099-12-31T18:00:00Z\",
    \"source_broadcast_id\": \"$BROADCAST_ID\"
  }")
OFFER_ID=$(echo "$OFFER" | jq -r '.offer_id // .id // empty')
assert_eq "Iggy sends offer" "$([ -n "$OFFER_ID" ] && echo true || echo false)" "true"

# Alice accepts → match created
ACCEPT=$(curl -s -X POST "$API/me/offers/$OFFER_ID/accept" \
  -H "Authorization: Bearer $ALICE")
MATCH_ID=$(echo "$ACCEPT" | jq -r '.match_id // empty')
if [ -z "$MATCH_ID" ]; then
  MATCH_ID=$(curl -s -H "Authorization: Bearer $ALICE" "$API/me/state" \
    | jq -r '.payload.active_match_id // empty')
fi
assert_eq "Alice accepts offer → match created" "$([ -n "$MATCH_ID" ] && echo true || echo false)" "true"

# Iggy submits score → pending_confirmation
SCORE1=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d '{
    "winner_uid": "user_ignatios",
    "score": {"sets": [{"p1_games": 6, "p2_games": 3}]}
  }')
assert_eq "Iggy submits score → pending_confirmation" \
  "$(echo "$SCORE1" | jq -r '.status // empty')" "pending_confirmation"

# Alice confirms → completed
SCORE2=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_ignatios"}')
assert_eq "Alice confirms score → completed" \
  "$(echo "$SCORE2" | jq -r '.status // empty')" "completed"

# Verify final match status in Firestore
MATCH_DOC=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "Match doc status=completed" \
  "$(echo "$MATCH_DOC" | jq -r '.fields.status.stringValue // empty')" "completed"

# ── Telemetry event assertions (log capture) ─────────────────────────────────
sleep 1  # let log lines flush

if [ "$LOG_CAPTURE" = "true" ]; then
  assert_log_contains "match_scheduled event emitted" '"event":"match_scheduled"'
  assert_log_contains "match_scheduled has match_id" "\"match_id\":\"$MATCH_ID\""
  assert_log_contains "score_submitted event emitted" '"event":"score_submitted"'
  assert_log_contains "score_confirmed event emitted" '"event":"score_confirmed"'
fi

# Cleanup between sections
curl -s -X DELETE "$FIRESTORE/matches/$MATCH_ID" > /dev/null || true
MATCH_ID=""
reset_playtab

# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Section 2: match_disputed event (singles) ────────────────────────────"
# ═══════════════════════════════════════════════════════════════════════════════

cleanup

# Alice broadcasts
BROADCAST2=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
BROADCAST_ID2=$(echo "$BROADCAST2" | jq -r '.broadcast_id // .id // empty')
assert_eq "Alice creates broadcast for dispute test" \
  "$([ -n "$BROADCAST_ID2" ] && echo true || echo false)" "true"

# Iggy sends offer
OFFER2=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"user_alice\",
    \"sport\": \"tennis\",
    \"proposed_time\": \"2099-12-31T18:00:00Z\",
    \"source_broadcast_id\": \"$BROADCAST_ID2\"
  }")
OFFER_ID2=$(echo "$OFFER2" | jq -r '.offer_id // .id // empty')
assert_eq "Iggy sends offer for dispute test" \
  "$([ -n "$OFFER_ID2" ] && echo true || echo false)" "true"

# Alice accepts
ACCEPT2=$(curl -s -X POST "$API/me/offers/$OFFER_ID2/accept" \
  -H "Authorization: Bearer $ALICE")
MATCH_ID=$(echo "$ACCEPT2" | jq -r '.match_id // empty')
if [ -z "$MATCH_ID" ]; then
  MATCH_ID=$(curl -s -H "Authorization: Bearer $ALICE" "$API/me/state" \
    | jq -r '.payload.active_match_id // empty')
fi
assert_eq "Alice accepts offer → match created" \
  "$([ -n "$MATCH_ID" ] && echo true || echo false)" "true"

# Iggy submits score claiming Iggy won
curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_ignatios", "score": {"sets": [{"p1_games": 6, "p2_games": 3}]}}' \
  > /dev/null

# Alice disputes — claims Alice won instead
DISPUTE=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_alice"}')
assert_eq "Alice disputes → status=disputed" \
  "$(echo "$DISPUTE" | jq -r '.status // empty')" "disputed"

MATCH_DOC2=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "Match doc status=disputed" \
  "$(echo "$MATCH_DOC2" | jq -r '.fields.status.stringValue // empty')" "disputed"

sleep 1

if [ "$LOG_CAPTURE" = "true" ]; then
  assert_log_contains "match_disputed event emitted" '"event":"match_disputed"'
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #318: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
