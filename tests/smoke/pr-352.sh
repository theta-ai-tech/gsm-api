#!/usr/bin/env bash
# Smoke tests for PR #352: feat: add GET /me/discovery intent-feed endpoint (#351)
# Generated: 2026-06-24
# Usage: bash tests/smoke/pr-352.sh
#
# Requires: make emu-all running + make seed-emu run once.
# The smoke-test skill starts the API automatically on port 8352.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8352}"
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

assert_gte() {
  local name="$1" actual="$2" min="$3"
  if [ "$actual" -ge "$min" ] 2>/dev/null; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (expected >= $min, got: $actual)"
    ((FAIL++)) || true
  fi
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (expected to contain '$needle')"
    echo "    actual: $haystack"
    ((FAIL++)) || true
  fi
}

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Tests ───────────────────────────────────────────────────────────────────

echo ""
echo "=== PR #352: GET /me/discovery smoke tests ==="
echo ""

# 1. Unauthenticated → 401
echo "--- Auth ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/me/discovery")
assert_eq "unauthenticated request returns 401" "$STATUS" "401"

# 2. Basic feed — top-level keys present
echo ""
echo "--- Basic feed (no filter) ---"
RESP=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/me/discovery")
HAS_SERVER_TIME=$(echo "$RESP" | jq 'has("serverTime")')
assert_eq "response has serverTime" "$HAS_SERVER_TIME" "true"

HAS_CLUBS=$(echo "$RESP" | jq 'has("activeClubsNearby")')
assert_eq "response has activeClubsNearby" "$HAS_CLUBS" "true"

HAS_INTENTS=$(echo "$RESP" | jq 'has("intents")')
assert_eq "response has intents" "$HAS_INTENTS" "true"

# 3. At least 2 seeded intents (user_alice have_court, user_bob need_court)
INTENT_COUNT=$(echo "$RESP" | jq '.intents | length')
assert_gte "at least 2 seeded intents" "$INTENT_COUNT" "2"

# 4. caller's own broadcast excluded (user_ignatios should not appear as toUid)
CALLER_IN_FEED=$(echo "$RESP" | jq '[.intents[].toUid] | map(select(. == "user_ignatios")) | length')
assert_eq "caller own broadcast excluded from feed" "$CALLER_IN_FEED" "0"

# 5. camelCase response shape on items
echo ""
echo "--- camelCase response shape ---"
ITEM_KEYS=$(echo "$RESP" | jq -c '[.intents[0] | keys[]] | sort')
assert_contains "item has broadcastId" "$ITEM_KEYS" "broadcastId"
assert_contains "item has courtStatus" "$ITEM_KEYS" "courtStatus"
assert_contains "item has expiresAt"   "$ITEM_KEYS" "expiresAt"
assert_contains "item has toUid"       "$ITEM_KEYS" "toUid"
assert_contains "item has availability" "$ITEM_KEYS" "availability"

# 6. Filter by sport=padel — all returned items are padel
echo ""
echo "--- Sport filter ---"
PADEL_RESP=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/me/discovery?sport=padel")
PADEL_COUNT=$(echo "$PADEL_RESP" | jq '.intents | length')
NON_PADEL=$(echo "$PADEL_RESP" | jq '[.intents[].sport] | map(select(. != "padel")) | length')
assert_eq "sport=padel filter: no non-padel items" "$NON_PADEL" "0"
assert_gte "sport=padel filter: at least 2 items" "$PADEL_COUNT" "2"

# 7. Filter by match_type=singles — all returned items are singles
echo ""
echo "--- Match type filter ---"
SINGLES_RESP=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/me/discovery?sport=padel&match_type=singles")
NON_SINGLES=$(echo "$SINGLES_RESP" | jq '[.intents[].matchType] | map(select(. != "singles")) | length')
assert_eq "match_type=singles filter: no non-singles items" "$NON_SINGLES" "0"

# 8. have_court item carries venueRef (not areaName)
echo ""
echo "--- Court status enrichment ---"
HAVE_COURT_ITEM=$(echo "$PADEL_RESP" | jq '[.intents[] | select(.courtStatus == "have_court")] | .[0]')
VENUE_REF=$(echo "$HAVE_COURT_ITEM" | jq '.venueRef')
assert_contains "have_court item has venueRef" "$VENUE_REF" "name"

# 9. need_court item carries areaName (not venueRef null check)
NEED_COURT_ITEM=$(echo "$PADEL_RESP" | jq '[.intents[] | select(.courtStatus == "need_court")] | .[0]')
AREA_NAME=$(echo "$NEED_COURT_ITEM" | jq -r '.areaName // "null"')
assert_eq "need_court item has areaName" "$AREA_NAME" "athens"

# 10. activeClubsNearby is a non-negative integer
CLUBS=$(echo "$RESP" | jq '.activeClubsNearby')
assert_gte "activeClubsNearby is non-negative" "$CLUBS" "0"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #352: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
