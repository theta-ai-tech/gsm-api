#!/usr/bin/env bash
# Smoke tests for PR #379: feat: GET /me/journal/loggable-matches — completed-matches
# picker with opponent + already_logged (#371)
# Generated: 2026-07-07
# Usage: bash tests/smoke/pr-379.sh
#
# Requires: make emu-all running + emulator seeded (make seed-emu).
# The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    ((FAIL++)) || true
  fi
}

firestore_patch() {
  # Usage: firestore_patch <collection/docId> <json-body> [field_mask...]
  local path="$1" body="$2"
  shift 2
  local url="$FIRESTORE/$path"
  local sep="?"
  local mask
  for mask in "$@"; do
    url="$url${sep}updateMask.fieldPaths=$mask"
    sep="&"
  done
  curl -s -X PATCH "$url" -H "Content-Type: application/json" -d "$body" > /dev/null
}

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# Sanity: seeded user doc must exist (PATCH would otherwise create a partial doc)
USER_EXISTS=$(curl -s "$FIRESTORE/users/user_ignatios" | jq -r '.fields.uid.stringValue // "missing"')
if [ "$USER_EXISTS" = "missing" ]; then
  echo "ERROR: users/user_ignatios not found in emulator. Run 'make seed-emu' first."
  exit 1
fi

ENDPOINT="$API/me/journal/loggable-matches"

# ── Tests ───────────────────────────────────────────────────────────────────

echo "PR #379 smoke: GET /me/journal/loggable-matches"

# Step 1: no auth → 401
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$ENDPOINT")
assert_eq "unauthenticated request rejected" "$CODE" "401"

# Step 2: seeded profile has empty completedMatches cache → []
firestore_patch "users/user_ignatios" '{"fields":{}}' "completedMatches" "journalRecent"
EMPTY=$(curl -s -H "Authorization: Bearer $TOKEN" "$ENDPOINT" | jq -c '.')
assert_eq "empty cache returns []" "$EMPTY" "[]"

# Step 3: seed completedMatches (2 entries, out of order) + journalRecent (logs match-completed-1)
firestore_patch "users/user_ignatios" '{
  "fields": {
    "completedMatches": {"arrayValue": {"values": [
      {"mapValue": {"fields": {
        "matchId": {"stringValue": "match-completed-2"},
        "sport": {"stringValue": "padel"},
        "finishedAt": {"timestampValue": "2020-01-10T18:00:00Z"},
        "result": {"stringValue": "loss"},
        "scoreText": {"stringValue": "3-6 4-6"},
        "leagueId": {"stringValue": "league-padel-local"},
        "opponentUid": {"stringValue": "user_alice"},
        "opponentName": {"stringValue": "Alice Papad"}
      }}},
      {"mapValue": {"fields": {
        "matchId": {"stringValue": "match-completed-1"},
        "sport": {"stringValue": "padel"},
        "finishedAt": {"timestampValue": "2020-01-20T18:00:00Z"},
        "result": {"stringValue": "win"},
        "scoreText": {"stringValue": "6-3 6-4"},
        "leagueId": {"stringValue": "league-padel-local"},
        "opponentUid": {"stringValue": "user_bob"},
        "opponentName": {"stringValue": "Bob Karv"}
      }}},
      {"mapValue": {"fields": {
        "matchId": {"stringValue": "match-legacy-no-opponent"},
        "sport": {"stringValue": "tennis"},
        "finishedAt": {"timestampValue": "2020-01-05T18:00:00Z"}
      }}}
    ]}},
    "journalRecent": {"arrayValue": {"values": [
      {"mapValue": {"fields": {
        "entryId": {"stringValue": "journal_1"},
        "createdAt": {"timestampValue": "2020-01-21T09:00:00Z"},
        "title": {"stringValue": "Padel win reflections"},
        "matchId": {"stringValue": "match-completed-1"},
        "sport": {"stringValue": "padel"},
        "entryType": {"stringValue": "match"}
      }}}
    ]}}
  }
}' "completedMatches" "journalRecent"

RESP=$(curl -s -H "Authorization: Bearer $TOKEN" "$ENDPOINT")

# Step 4: assertions on the enriched response
assert_eq "returns 3 items" "$(echo "$RESP" | jq 'length')" "3"
assert_eq "ordered finished_at DESC (first = match-completed-1)" \
  "$(echo "$RESP" | jq -r '.[0].match_id')" "match-completed-1"
assert_eq "ordered finished_at DESC (last = legacy)" \
  "$(echo "$RESP" | jq -r '.[2].match_id')" "match-legacy-no-opponent"
assert_eq "opponent_uid populated" "$(echo "$RESP" | jq -r '.[0].opponent_uid')" "user_bob"
assert_eq "opponent_name populated" "$(echo "$RESP" | jq -r '.[0].opponent_name')" "Bob Karv"
assert_eq "score_text passed through" "$(echo "$RESP" | jq -r '.[0].score_text')" "6-3 6-4"
assert_eq "result passed through" "$(echo "$RESP" | jq -r '.[0].result')" "win"
assert_eq "league_id passed through" "$(echo "$RESP" | jq -r '.[0].league_id')" "league-padel-local"
assert_eq "already_logged true for journaled match" \
  "$(echo "$RESP" | jq -r '.[0].already_logged')" "true"
assert_eq "already_logged false for unlogged match" \
  "$(echo "$RESP" | jq -r '.[1].already_logged')" "false"
assert_eq "legacy entry opponent_uid null" \
  "$(echo "$RESP" | jq -r '.[2].opponent_uid')" "null"
assert_eq "legacy entry opponent_name null" \
  "$(echo "$RESP" | jq -r '.[2].opponent_name')" "null"

# ── Teardown ────────────────────────────────────────────────────────────────
firestore_patch "users/user_ignatios" '{"fields":{
  "completedMatches": {"arrayValue": {}},
  "journalRecent": {"arrayValue": {}}
}}' "completedMatches" "journalRecent"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #379: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
