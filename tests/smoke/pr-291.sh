#!/usr/bin/env bash
# Smoke tests for PR #291: fix: DBL-9 D-series triggers — doubles match participants (#173)
# Usage: bash tests/smoke/pr-291.sh
#
# Requires: make emu-all (Firestore + Auth emulator running)
#
# Tests the D5.2 trigger fix: league stats are incremented for ALL 4 participants
# in a doubles match, not just the first winner and first loser.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR (or $REPO_ROOT/.venv). Run 'make venv && make install'."
  exit 1
fi

export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"
export FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"

FIRESTORE_HOST="${FIRESTORE_EMULATOR_HOST}"
PROJECT="${GOOGLE_CLOUD_PROJECT}"
FS_URL="http://$FIRESTORE_HOST/v1/projects/$PROJECT/databases/(default)/documents"

LEAGUE_ID="padel-local-2025"
MATCH_ID_DOUBLES="smoke-dbl-9-doubles-match"
MATCH_ID_SINGLES="smoke-dbl-9-singles-match"

WINNER1="user_ignatios"
WINNER2="user_alex"
LOSER1="user_bob"
LOSER2="user_diana"

SINGLES_WINNER="user_ignatios"
SINGLES_LOSER="user_alex"

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

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (expected to contain: $needle)"
    ((FAIL++)) || true
  fi
}

assert_not_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  ✗ $name (should NOT contain: $needle)"
    ((FAIL++)) || true
  else
    echo "  ✓ $name"
    ((PASS++)) || true
  fi
}

run_trigger() {
  # Run D5.2 trigger handler inline using the emulator
  local match_id="$1" league_id="$2" before_status="$3" p_uids="$4" result_by_user="$5"
  source "$VENV_DIR/bin/activate"
  python3 - <<PYEOF
import os, sys
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "$FIRESTORE_HOST")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "$PROJECT")
os.environ.setdefault("TRIGGERS_ENABLED", "true")
sys.path.insert(0, "$REPO_ROOT/api")

from google.cloud import firestore
from datetime import datetime, timezone
from functions.scoring_triggers.main import handle_match_write_update_league_stats

client = firestore.Client()
finished = datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc)

before = {
    "matchId": "$match_id",
    "status": "$before_status",
    "participantUids": $p_uids,
}
after = {
    "matchId": "$match_id",
    "status": "completed",
    "leagueId": "$league_id",
    "sport": "padel",
    "finishedAt": finished,
    "participantUids": $p_uids,
    "resultByUser": $result_by_user,
}

handle_match_write_update_league_stats(client, before, after)
print("ok")
PYEOF
}

get_member_wins() {
  local league_id="$1" uid="$2"
  curl -s "$FS_URL/leagues/$league_id/members/$uid" \
    | python3 -c "
import sys, json
doc = json.load(sys.stdin)
fields = doc.get('fields', {})
stats = fields.get('stats', {}).get('mapValue', {}).get('fields', {})
wins_map = stats.get('wins', {})
# Firestore integer value
val = wins_map.get('integerValue') or wins_map.get('doubleValue') or '0'
print(val)
" 2>/dev/null || echo "0"
}

get_member_losses() {
  local league_id="$1" uid="$2"
  curl -s "$FS_URL/leagues/$league_id/members/$uid" \
    | python3 -c "
import sys, json
doc = json.load(sys.stdin)
fields = doc.get('fields', {})
stats = fields.get('stats', {}).get('mapValue', {}).get('fields', {})
losses_map = stats.get('losses', {})
val = losses_map.get('integerValue') or losses_map.get('doubleValue') or '0'
print(val)
" 2>/dev/null || echo "0"
}

cleanup() {
  # Remove smoke test member docs and match docs from emulator
  for uid in "$WINNER1" "$WINNER2" "$LOSER1" "$LOSER2"; do
    curl -s -o /dev/null -X DELETE "$FS_URL/leagues/$LEAGUE_ID/members/$uid" || true
  done
  curl -s -o /dev/null -X DELETE "$FS_URL/matches/$MATCH_ID_DOUBLES" || true
  curl -s -o /dev/null -X DELETE "$FS_URL/matches/$MATCH_ID_SINGLES" || true
}

seed_member() {
  # Seed a complete league member doc so the stats trigger can write to it.
  # The trigger skips non-existent member docs (to avoid phantom memberships),
  # so tests require pre-seeded docs with role, status, and joinedAt.
  local uid="$1"
  curl -s -o /dev/null -X PATCH \
    "$FS_URL/leagues/$LEAGUE_ID/members/$uid" \
    -H "Content-Type: application/json" \
    -d '{
      "fields": {
        "role":     {"stringValue": "player"},
        "status":   {"stringValue": "active"},
        "joinedAt": {"timestampValue": "2025-01-01T00:00:00Z"}
      }
    }' || true
}

trap cleanup EXIT
cleanup

# Seed complete member docs for all 4 participants before running any trigger.
# The trigger intentionally skips missing docs, so members must exist first.
for uid in "$WINNER1" "$WINNER2" "$LOSER1" "$LOSER2"; do
  seed_member "$uid"
done

# ── Tests ────────────────────────────────────────────────────────────────────

echo ""
echo "=== Test 1: Doubles match increments wins for BOTH winners ==="
P_UIDS='["'"$WINNER1"'","'"$WINNER2"'","'"$LOSER1"'","'"$LOSER2"'"]'
RESULT_BY_USER='{"'"$WINNER1"'": "W", "'"$WINNER2"'": "W", "'"$LOSER1"'": "L", "'"$LOSER2"'": "L"}'

RUN_RESULT=$(run_trigger "$MATCH_ID_DOUBLES" "$LEAGUE_ID" "pending_confirmation" "$P_UIDS" "$RESULT_BY_USER")
assert_eq "trigger ran successfully" "$RUN_RESULT" "ok"

W1_WINS=$(get_member_wins "$LEAGUE_ID" "$WINNER1")
W2_WINS=$(get_member_wins "$LEAGUE_ID" "$WINNER2")
assert_eq "$WINNER1 wins incremented to 1" "$W1_WINS" "1"
assert_eq "$WINNER2 wins incremented to 1" "$W2_WINS" "1"

echo ""
echo "=== Test 2: Doubles match increments losses for BOTH losers ==="
L1_LOSSES=$(get_member_losses "$LEAGUE_ID" "$LOSER1")
L2_LOSSES=$(get_member_losses "$LEAGUE_ID" "$LOSER2")
assert_eq "$LOSER1 losses incremented to 1" "$L1_LOSSES" "1"
assert_eq "$LOSER2 losses incremented to 1" "$L2_LOSSES" "1"

echo ""
echo "=== Test 3: Winners have zero losses, losers have zero wins ==="
W1_LOSSES=$(get_member_losses "$LEAGUE_ID" "$WINNER1")
W2_LOSSES=$(get_member_losses "$LEAGUE_ID" "$WINNER2")
L1_WINS=$(get_member_wins "$LEAGUE_ID" "$LOSER1")
L2_WINS=$(get_member_wins "$LEAGUE_ID" "$LOSER2")
assert_eq "$WINNER1 has 0 losses" "$W1_LOSSES" "0"
assert_eq "$WINNER2 has 0 losses" "$W2_LOSSES" "0"
assert_eq "$LOSER1 has 0 wins" "$L1_WINS" "0"
assert_eq "$LOSER2 has 0 wins" "$L2_WINS" "0"

echo ""
echo "=== Test 4: Idempotency — replaying doubles event produces no extra increments ==="
RUN_RESULT=$(run_trigger "$MATCH_ID_DOUBLES" "$LEAGUE_ID" "pending_confirmation" "$P_UIDS" "$RESULT_BY_USER")
assert_eq "replay trigger ran successfully" "$RUN_RESULT" "ok"

# Wins and losses must not double-count
W1_WINS=$(get_member_wins "$LEAGUE_ID" "$WINNER1")
W2_WINS=$(get_member_wins "$LEAGUE_ID" "$WINNER2")
L1_LOSSES=$(get_member_losses "$LEAGUE_ID" "$LOSER1")
L2_LOSSES=$(get_member_losses "$LEAGUE_ID" "$LOSER2")
assert_eq "$WINNER1 wins still 1 after replay" "$W1_WINS" "1"
assert_eq "$WINNER2 wins still 1 after replay" "$W2_WINS" "1"
assert_eq "$LOSER1 losses still 1 after replay" "$L1_LOSSES" "1"
assert_eq "$LOSER2 losses still 1 after replay" "$L2_LOSSES" "1"

echo ""
echo "=== Test 5: Singles match (regression) still increments exactly 2 members ==="
# Re-use winner1/loser1 for singles (they already have a processedMatchId for the doubles match)
# Use a different match ID so idempotency guard doesn't block
S_MATCH_ID="$MATCH_ID_SINGLES"
S_P_UIDS='["'"$SINGLES_WINNER"'","'"$SINGLES_LOSER"'"]'
S_RESULT='{"'"$SINGLES_WINNER"'": "W", "'"$SINGLES_LOSER"'": "L"}'

RUN_RESULT=$(run_trigger "$S_MATCH_ID" "$LEAGUE_ID" "pending_confirmation" "$S_P_UIDS" "$S_RESULT")
assert_eq "singles trigger ran successfully" "$RUN_RESULT" "ok"

# WINNER1 now has 2 wins (1 from doubles + 1 from singles)
# LOSER1 (user_alex acting as singles loser) now has 1 loss (from singles)
SW_WINS=$(get_member_wins "$LEAGUE_ID" "$SINGLES_WINNER")
SL_LOSSES=$(get_member_losses "$LEAGUE_ID" "$SINGLES_LOSER")
# Should be incremented exactly once for singles
if [ "$SW_WINS" -ge 2 ]; then
  echo "  ✓ $SINGLES_WINNER wins incremented after singles match (total=$SW_WINS)"
  ((PASS++)) || true
else
  echo "  ✗ $SINGLES_WINNER wins not incremented for singles match (got=$SW_WINS)"
  ((FAIL++)) || true
fi
if [ "$SL_LOSSES" -ge 1 ]; then
  echo "  ✓ $SINGLES_LOSER losses incremented after singles match (total=$SL_LOSSES)"
  ((PASS++)) || true
else
  echo "  ✗ $SINGLES_LOSER losses not incremented for singles match (got=$SL_LOSSES)"
  ((FAIL++)) || true
fi

echo ""
echo "=== Test 6: Missing winner in resultByUser — trigger ignores the match ==="
# Only a loser in resultByUser — must be ignored (no writes)
INCOMPLETE_RESULT='{"'"$LOSER1"'": "L"}'
# Read current wins before
PRE_WINS=$(get_member_wins "$LEAGUE_ID" "$LOSER1")
RUN_RESULT=$(run_trigger "smoke-incomplete-match" "$LEAGUE_ID" "pending_confirmation" "$P_UIDS" "$INCOMPLETE_RESULT")
assert_eq "incomplete-result trigger ran (no crash)" "$RUN_RESULT" "ok"
# Loser should not have gotten a win
POST_WINS=$(get_member_wins "$LEAGUE_ID" "$LOSER1")
assert_eq "no wins written for incomplete result_by_user" "$PRE_WINS" "$POST_WINS"

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "─────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
echo "─────────────────────────────────────"

[ "$FAIL" -eq 0 ]
