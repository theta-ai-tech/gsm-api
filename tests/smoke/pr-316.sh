#!/usr/bin/env bash
# Smoke test for PR #316 — OPS-1: Seed launch-ready Athens demo data
# Usage: bash tests/smoke/pr-316.sh
# Requires: Firestore emulator running at 127.0.0.1:8082
#           GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0

set -euo pipefail

EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
BASE_URL="http://${EMULATOR_HOST}/v1/projects/${PROJECT}/databases/(default)/documents"

PASS=0
FAIL=0

check() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS  $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $label"
    echo "        expected: $expected"
    echo "        actual:   $actual"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "=== PR #316 Smoke Tests: OPS-1 Athens Demo Seed Data ==="
echo ""

# Seed the data first
echo "--- Seeding Firestore emulator ---"
FIRESTORE_EMULATOR_HOST="$EMULATOR_HOST" GOOGLE_CLOUD_PROJECT="$PROJECT" \
  python tools/seed_firestore.py
echo ""

echo "--- Diana user ---"
DIANA=$(curl -sf "${BASE_URL}/users/user_diana")
check "Diana displayName" "$(echo "$DIANA" | jq -r '.fields.displayName.stringValue')" "Diana"
check "Diana area" "$(echo "$DIANA" | jq -r '.fields.area.integerValue')" "101"
check "Diana sport" "$(echo "$DIANA" | jq -r '.fields.preferredSport.stringValue')" "padel"
check "Diana ranking pts" "$(echo "$DIANA" | jq -r '.fields.rankings.mapValue.fields.padel.mapValue.fields.pts.integerValue')" "710"

echo ""
echo "--- Diana league membership ---"
DIANA_MEMBER=$(curl -sf "${BASE_URL}/leagues/padel-local-2025/members/user_diana")
check "Diana league role" "$(echo "$DIANA_MEMBER" | jq -r '.fields.role.stringValue')" "player"

echo ""
echo "--- Upcoming doubles match ---"
UPCOMING=$(curl -sf "${BASE_URL}/matches/match-upcoming-doubles")
check "Upcoming matchType" "$(echo "$UPCOMING" | jq -r '.fields.matchType.stringValue')" "doubles"
check "Upcoming status" "$(echo "$UPCOMING" | jq -r '.fields.status.stringValue')" "scheduled"
check "Upcoming sport" "$(echo "$UPCOMING" | jq -r '.fields.sport.stringValue')" "padel"

echo ""
echo "--- Completed doubles match ---"
COMPLETED=$(curl -sf "${BASE_URL}/matches/match-completed-doubles")
check "Completed matchType" "$(echo "$COMPLETED" | jq -r '.fields.matchType.stringValue')" "doubles"
check "Completed status" "$(echo "$COMPLETED" | jq -r '.fields.status.stringValue')" "completed"
check "Completed winnerTeam" "$(echo "$COMPLETED" | jq -r '.fields.score.mapValue.fields.winnerTeam.stringValue')" "A"

echo ""
echo "--- Venue suggestions ---"
VS1=$(curl -sf "${BASE_URL}/venueSuggestions/suggestion-seed-1")
check "Venue suggestion 1 name" "$(echo "$VS1" | jq -r '.fields.name.stringValue')" "Kifissia Padel Club"
check "Venue suggestion 1 status" "$(echo "$VS1" | jq -r '.fields.status.stringValue')" "pending"

VS2=$(curl -sf "${BASE_URL}/venueSuggestions/suggestion-seed-2")
check "Venue suggestion 2 name" "$(echo "$VS2" | jq -r '.fields.name.stringValue')" "Maroussi Sports Center"
check "Venue suggestion 2 status" "$(echo "$VS2" | jq -r '.fields.status.stringValue')" "pending"

echo ""
echo "--- Point history for Diana ---"
PH=$(curl -sf "${BASE_URL}/users/user_diana/pointHistory/ph_diana_padel_dbl_1")
check "Diana PH reason" "$(echo "$PH" | jq -r '.fields.reason.stringValue')" "match_doubles_win"
check "Diana PH pts" "$(echo "$PH" | jq -r '.fields.pts.integerValue')" "710"

echo ""
echo "========================================"
echo "Results: ${PASS} passed, ${FAIL} failed"
echo "========================================"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
