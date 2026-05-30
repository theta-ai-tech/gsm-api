#!/usr/bin/env bash
# Smoke tests for PR #317: feat: OBS-2 emit telemetry events for broadcast and offer lifecycle (#279)
# Generated: 2026-05-31
# Usage: bash tests/smoke/pr-317.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8317}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"
LOG_FILE="${LOG_FILE:-/tmp/gsm-api-pr-317.log}"

# ── Venv resolution ──────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="${MAIN_WT}/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
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

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected to contain: $needle"
    echo "    actual: $haystack"
    ((FAIL++)) || true
  fi
}

assert_log_event() {
  # Greps LOG_FILE for an analytics event JSON line containing the given key=value pair.
  # Usage: assert_log_event "test name" "event_key" "event_value"
  local name="$1" key="$2" value="$3"
  sleep 0.3  # allow log flush
  if grep -q "\"$key\":\"$value\"" "$LOG_FILE" 2>/dev/null; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    log line with \"$key\":\"$value\" not found in $LOG_FILE"
    ((FAIL++)) || true
  fi
}

firestore_patch() {
  local path="$1" body="$2" mask="${3:-}"
  local url="$FIRESTORE/$path"
  [ -n "$mask" ] && url="${url}?updateMask.fieldPaths=${mask}"
  curl -s -X PATCH "$url" -H "Content-Type: application/json" -d "$body" > /dev/null
}

# ── Reset user states to DISCOVERY ───────────────────────────────────────────

reset_user_state() {
  local uid="$1"
  firestore_patch "users/$uid" \
    '{"fields":{"playTab":{"mapValue":{"fields":{"state":{"stringValue":"DISCOVERY"},"activeBroadcastId":{"nullValue":null},"activeOutgoingOfferId":{"nullValue":null},"pendingIncomingOfferIds":{"arrayValue":{"values":[]}},"activeMatchId":{"nullValue":null}}}}}}' \
    "playTab"
}

# ── Token acquisition ─────────────────────────────────────────────────────────
echo "→ Acquiring tokens..."
TOKEN_ALICE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
TOKEN_BOB=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_bob -t 2>/dev/null)

if [ -z "$TOKEN_ALICE" ] || [ -z "$TOKEN_BOB" ]; then
  echo "ERROR: Could not get auth tokens. Is the auth emulator running?"
  exit 1
fi

# ── Setup: reset user states ──────────────────────────────────────────────────
echo "→ Resetting user states to DISCOVERY..."
reset_user_state "user_alice"
reset_user_state "user_bob"
sleep 0.2

# ── Test 1: POST /me/broadcast — broadcast_created event ─────────────────────
echo ""
echo "Test 1: Create broadcast (broadcast_created telemetry)"

EXPIRES=$(date -u -v+2H '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '+2 hours' '+%Y-%m-%dT%H:%M:%SZ')

BROADCAST_RESP=$(curl -s -w "\n%{http_code}" -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $TOKEN_ALICE" \
  -H "Content-Type: application/json" \
  -d "{\"sport\":\"tennis\",\"availability\":\"today\",\"courtStatus\":\"have_court\",\"courtLocation\":\"Test Court Athens\",\"expiresAt\":\"$EXPIRES\",\"location\":{\"area\":10001}}")

HTTP_CODE=$(echo "$BROADCAST_RESP" | tail -1)
BROADCAST_BODY=$(echo "$BROADCAST_RESP" | head -1)

assert_eq "broadcast created — HTTP 201" "$HTTP_CODE" "201"
BROADCAST_ID=$(echo "$BROADCAST_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('broadcast_id',''))" 2>/dev/null || echo "")
assert_contains "broadcast response has broadcast_id" "$BROADCAST_BODY" "broadcast_id"
assert_eq "broadcast sport=tennis" "$(echo "$BROADCAST_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sport',''))" 2>/dev/null)" "tennis"

assert_log_event "log: broadcast_created event" "event" "broadcast_created"
assert_log_event "log: broadcast_created uid=user_alice" "uid" "user_alice"

# ── Test 2: POST /me/offers — offer_sent + offer_received events ─────────────
echo ""
echo "Test 2: Send offer (offer_sent + offer_received telemetry)"

FUTURE_TIME=$(date -u -v+3H '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '+3 hours' '+%Y-%m-%dT%H:%M:%SZ')

# bob needs to be in DISCOVERY; alice created broadcast so she's BROADCAST_ACTIVE
# alice (user_alice) is the broadcast owner, bob sends offer to alice
OFFER_RESP=$(curl -s -w "\n%{http_code}" -X POST "$API/me/offers" \
  -H "Authorization: Bearer $TOKEN_BOB" \
  -H "Content-Type: application/json" \
  -d "{\"toUid\":\"user_alice\",\"sport\":\"tennis\",\"proposedTime\":\"$FUTURE_TIME\",\"courtLocation\":\"Test Court Athens\",\"sourceBroadcastId\":\"$BROADCAST_ID\"}")

HTTP_CODE=$(echo "$OFFER_RESP" | tail -1)
OFFER_BODY=$(echo "$OFFER_RESP" | head -1)

assert_eq "offer sent — HTTP 200" "$HTTP_CODE" "200"
OFFER_ID=$(echo "$OFFER_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('offer_id',''))" 2>/dev/null || echo "")
assert_contains "offer response has offer_id" "$OFFER_BODY" "offer_id"

assert_log_event "log: offer_sent event" "event" "offer_sent"
assert_log_event "log: offer_sent uid=user_bob (sender)" "uid" "user_bob"
assert_log_event "log: offer_received event" "event" "offer_received"

# ── Test 3: POST /me/offers/{id}/accept — offer_accepted event ───────────────
echo ""
echo "Test 3: Accept offer (offer_accepted telemetry)"

if [ -z "$OFFER_ID" ]; then
  echo "  ✗ accept offer — skipped (no offer_id from previous step)"
  ((FAIL++)) || true
else
  ACCEPT_RESP=$(curl -s -w "\n%{http_code}" -X POST "$API/me/offers/$OFFER_ID/accept" \
    -H "Authorization: Bearer $TOKEN_ALICE")

  HTTP_CODE=$(echo "$ACCEPT_RESP" | tail -1)
  ACCEPT_BODY=$(echo "$ACCEPT_RESP" | head -1)

  assert_eq "offer accepted — HTTP 200" "$HTTP_CODE" "200"
  assert_eq "offer accepted status=accepted" \
    "$(echo "$ACCEPT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)" \
    "accepted"

  assert_log_event "log: offer_accepted event" "event" "offer_accepted"
  assert_log_event "log: offer_accepted uid=user_alice" "uid" "user_alice"
fi

# ── Teardown ──────────────────────────────────────────────────────────────────
echo ""
echo "→ Teardown: resetting user states..."
reset_user_state "user_alice"
reset_user_state "user_bob"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #317: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
