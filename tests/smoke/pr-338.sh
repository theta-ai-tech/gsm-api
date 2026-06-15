#!/usr/bin/env bash
# Smoke tests for PR #338: docs: tested dispute-resolution runbook (#327)
# Generated: 2026-06-15
# Usage: bash tests/smoke/pr-338.sh
#
# Requires: make emu-all running + seeded (make seed-emu). The smoke-test skill
# starts the PR-scoped API. This script exercises the OPS-DISPUTE-1 runbook end
# to end: drive a genuine singles dispute via the API, then apply the runbook's
# Outcome A (void the match) and assert all participants are released to
# DISCOVERY and the match is cancelled.
#
# NOTE: the emulator enforces prod-style security rules (post SEC-1/#337), so
# raw Firestore REST calls use the "Authorization: Bearer owner" rule-bypass
# header (consistent with the operator playbook).

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"
MATCH_ID="match-upcoming-2"

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

# ── Firestore helpers (owner header bypasses prod rules) ─────────────────────
fs_get_field() {
  # Usage: fs_get_field <collection/docId> <jq-path>
  curl -s -H "Authorization: Bearer owner" "$FIRESTORE/$1" | jq -r "$2 // \"null\""
}

reset_match_scheduled() {
  # Reset match-upcoming-2 back to its seeded SCHEDULED state and drop the
  # mutated fields (score / resultByUser / resultSubmittedBy). Deleting fields
  # via REST = listing them in updateMask but omitting them from the body.
  curl -s -X PATCH -H "Authorization: Bearer owner" -H "Content-Type: application/json" \
    "$FIRESTORE/matches/$MATCH_ID?updateMask.fieldPaths=status&updateMask.fieldPaths=score&updateMask.fieldPaths=resultByUser&updateMask.fieldPaths=resultSubmittedBy" \
    -d '{"fields":{"status":{"stringValue":"scheduled"}}}' > /dev/null
}

release_user() {
  # Usage: release_user <uid>  -> playTab.state=DISCOVERY, activeMatchId=null
  curl -s -X PATCH -H "Authorization: Bearer owner" -H "Content-Type: application/json" \
    "$FIRESTORE/users/$1?updateMask.fieldPaths=playTab.state&updateMask.fieldPaths=playTab.activeMatchId" \
    -d '{"fields":{"playTab":{"mapValue":{"fields":{"state":{"stringValue":"DISCOVERY"},"activeMatchId":{"nullValue":null}}}}}}' > /dev/null
}

# ── Tokens for the two seeded participants ──────────────────────────────────
TI=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
TA=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
if [ -z "$TI" ] || [ -z "$TA" ]; then
  echo "ERROR: could not get auth tokens for user_ignatios / user_alice. Is the auth emulator running and seeded?"
  exit 1
fi

# Pre-test reset so the script is rerunnable even if a prior run left the match
# cancelled/disputed.
reset_match_scheduled
release_user user_ignatios
release_user user_alice

echo ""
echo "── PR #338: dispute-resolution runbook smoke ──"

# ── 1. Drive a genuine singles dispute ──────────────────────────────────────
SCORE_A='{"winner_uid":"user_alice","score":{"sets":[{"p1_games":6,"p2_games":4},{"p1_games":6,"p2_games":3}],"winner_uid":"user_alice"}}'
SCORE_I='{"winner_uid":"user_ignatios","score":{"sets":[{"p1_games":6,"p2_games":4},{"p1_games":6,"p2_games":3}],"winner_uid":"user_ignatios"}}'

S1=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TA" -H "Content-Type: application/json" \
  -d "$SCORE_A" | jq -r '.status // "null"')
assert_eq "first submission (alice) -> pending_confirmation" "$S1" "pending_confirmation"

S2=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TI" -H "Content-Type: application/json" \
  -d "$SCORE_I" | jq -r '.status // "null"')
assert_eq "second submission (ignatios, disagrees) -> disputed" "$S2" "disputed"

# Step 0 — inspect: confirm the match doc is genuinely disputed.
MSTATUS=$(fs_get_field "matches/$MATCH_ID" '.fields.status.stringValue')
assert_eq "match doc status == disputed" "$MSTATUS" "disputed"

# ── 2. Outcome A — void the match + release every participant ───────────────
curl -s -X PATCH -H "Authorization: Bearer owner" -H "Content-Type: application/json" \
  "$FIRESTORE/matches/$MATCH_ID?updateMask.fieldPaths=status" \
  -d '{"fields":{"status":{"stringValue":"cancelled"}}}' > /dev/null
release_user user_ignatios
release_user user_alice

# ── 3. Assert release ───────────────────────────────────────────────────────
MSTATUS2=$(fs_get_field "matches/$MATCH_ID" '.fields.status.stringValue')
assert_eq "match voided -> status == cancelled" "$MSTATUS2" "cancelled"

MODE_I=$(curl -s "$API/me/state" -H "Authorization: Bearer $TI" | jq -r '.mode // "null"')
assert_eq "ignatios released -> /me/state mode == DISCOVERY" "$MODE_I" "DISCOVERY"

MODE_A=$(curl -s "$API/me/state" -H "Authorization: Bearer $TA" | jq -r '.mode // "null"')
assert_eq "alice released -> /me/state mode == DISCOVERY" "$MODE_A" "DISCOVERY"

AMI_I=$(fs_get_field "users/user_ignatios" '.fields.playTab.mapValue.fields.activeMatchId.nullValue')
assert_eq "ignatios playTab.activeMatchId cleared" "$AMI_I" "null"

# ── Teardown — restore seeded SCHEDULED state so reruns are idempotent ───────
reset_match_scheduled
release_user user_ignatios
release_user user_alice

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #338: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
