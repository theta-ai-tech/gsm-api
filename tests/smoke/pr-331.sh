#!/usr/bin/env bash
# Smoke tests for PR #331: fix: re-assert match status inside completion txn (#320)
# Generated: 2026-06-01
# Usage: bash tests/smoke/pr-331.sh
#
# Requires: make emu-all running. This script starts the PR API itself.
#
# Verifies the double-scoring race guard:
#   - The confirming player's first verify-score call completes the match (200).
#   - A duplicate verify-score from the same player is rejected with 409
#     "already completed" — points are awarded exactly once.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8331}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/$PROJECT/databases/(default)/documents"
LOG_FILE="/tmp/gsm-api-pr-331-smoke.log"
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

# ── Start API ─────────────────────────────────────────────────────────────────
API_PORT="${API_PORT:-8331}"

if curl -fsS "$API/health" >/dev/null 2>&1; then
  echo "Using pre-started API at $API"
else
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
echo "── Section 1: duplicate completion is rejected with 409 ────────────────────"
# ═══════════════════════════════════════════════════════════════════════════════

# Alice broadcasts
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
assert_eq "Alice accepts offer → match created" \
  "$([ -n "$MATCH_ID" ] && echo true || echo false)" "true"

# Iggy submits score (first submission) → pending_confirmation
SCORE1=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d '{
    "winner_uid": "user_ignatios",
    "score": {"sets": [{"p1_games": 6, "p2_games": 3}]}
  }')
assert_eq "Iggy submits score → pending_confirmation" \
  "$(echo "$SCORE1" | jq -r '.status // empty')" "pending_confirmation"

# Alice confirms (second submission, opposing player) → match completes
SCORE2=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_ignatios"}')
assert_eq "Alice confirms → completed" \
  "$(echo "$SCORE2" | jq -r '.status // empty')" "completed"

# Verify match doc is completed in Firestore
MATCH_DOC=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "Match doc status=completed after confirmation" \
  "$(echo "$MATCH_DOC" | jq -r '.fields.status.stringValue // empty')" "completed"

# Alice tries to confirm AGAIN (duplicate) → must be rejected with 409
BODY_FILE=$(mktemp)
DUP_CODE=$(curl -s -o "$BODY_FILE" -w "%{http_code}" \
  -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_ignatios"}')
DUP_DETAIL=$(jq -r '.detail // empty' "$BODY_FILE")
rm -f "$BODY_FILE"
assert_eq "Duplicate confirmation rejected with 409" "$DUP_CODE" "409"
assert_eq "409 detail mentions status" \
  "$(echo "$DUP_DETAIL" | grep -c "status\|completed\|already" || echo 0)" "1"

# Match must still be completed (duplicate did NOT corrupt it)
MATCH_DOC2=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "Match doc still completed after duplicate attempt" \
  "$(echo "$MATCH_DOC2" | jq -r '.fields.status.stringValue // empty')" "completed"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #331: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
