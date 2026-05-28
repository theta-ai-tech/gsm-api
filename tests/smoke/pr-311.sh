#!/usr/bin/env bash
# Smoke tests for PR #311: docs: DOC-1 freeze mobile launch API contracts (#272)
# Generated: 2026-05-27
# Usage: bash tests/smoke/pr-311.sh
#
# Documentation-only PR — no running API or emulator required.
# Validates that the expected content exists in the three changed files.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

assert_contains() {
  local name="$1" file="$2" pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    pattern not found: $pattern"
    echo "    file: $file"
    ((FAIL++)) || true
  fi
}

assert_file_exists() {
  local name="$1" file="$2"
  if [ -f "$file" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    file not found: $file"
    ((FAIL++)) || true
  fi
}

CONTRACTS="$REPO_ROOT/spec/api-launch-contracts.md"
ENDPOINTS="$REPO_ROOT/wiki/endpoints.md"
PAYLOADS="$REPO_ROOT/spec/tab1-play-payloads.md"

echo ""
echo "── spec/api-launch-contracts.md ──────────────────────────────────────────────"

assert_file_exists "api-launch-contracts.md exists" "$CONTRACTS"
assert_contains "POST /me/broadcast documented" "$CONTRACTS" "POST /me/broadcast"
assert_contains "POST /me/offers documented" "$CONTRACTS" "POST /me/offers"
assert_contains "POST /me/offers uses snake_case to_uid" "$CONTRACTS" '"to_uid"'
assert_contains "POST /me/offers uses snake_case proposed_time" "$CONTRACTS" '"proposed_time"'
assert_contains "POST /me/offers response uses snake_case offer_id" "$CONTRACTS" '"offer_id"'
assert_contains "POST /me/offers/{id}/accept response uses snake_case match_id" "$CONTRACTS" '"match_id"'
assert_contains "GET /me/state envelope uses snake_case server_time" "$CONTRACTS" '"server_time"'
assert_contains "GET /me/state envelope uses snake_case active_offer_ids" "$CONTRACTS" '"active_offer_ids"'
assert_contains "GET /me/state has match_type query param" "$CONTRACTS" "match_type"
assert_contains "availability enum has tomorrow" "$CONTRACTS" '"tomorrow"'
assert_contains "availability enum has weekend" "$CONTRACTS" '"weekend"'
assert_contains "MatchScore uses snake_case p1_games" "$CONTRACTS" '"p1_games"'
assert_contains "POST /me/offers/{offerId}/accept documented" "$CONTRACTS" "accept"
assert_contains "POST /matches/{matchId}/verify-score documented" "$CONTRACTS" "verify-score"
assert_contains "GET /me/state documented" "$CONTRACTS" "GET /me/state"
assert_contains "GET /venues/search documented" "$CONTRACTS" "GET /venues/search"
assert_contains "GET /venues documented" "$CONTRACTS" "GET /venues"
assert_contains "POST /venues/suggest documented" "$CONTRACTS" "POST /venues/suggest"
assert_contains "Doubles example present (match_type: doubles)" "$CONTRACTS" "match_type.*doubles\|doubles.*match_type"
assert_contains "winner_team doubles field present" "$CONTRACTS" "winner_team"
assert_contains "Known Limitations section present" "$CONTRACTS" "Known Limitations"
assert_contains "Dispute resolution limitation noted" "$CONTRACTS" "dispute"
assert_contains "venueRef not echoed limitation noted" "$CONTRACTS" "venueRef\|venue_ref"
assert_contains "Offer expiry limitation noted" "$CONTRACTS" "5.min\|5 min\|expiry\|expir"
assert_contains "venues/search Google Places key limitation noted" "$CONTRACTS" "Google Places\|Places API"
assert_contains "verify-score naming clarification present" "$CONTRACTS" "result.*confirm\|confirm.*result\|result/confirm"
assert_contains "broadcast location uses radius_km not radiusKm" "$CONTRACTS" '"radius_km"'

echo ""
echo "── wiki/endpoints.md ─────────────────────────────────────────────────────────"

assert_contains "GET /venues/search section exists" "$ENDPOINTS" "GET \`/venues/search\`\|## \`GET /venues/search\`"
assert_contains "GET /venues/search has query param q" "$ENDPOINTS" "| \`q\`\| q "
assert_contains "GET /venues/search has call example" "$ENDPOINTS" "venues/search?q="
assert_contains "GET /venues/search response example" "$ENDPOINTS" "results.*venueId\|venueId.*results"
assert_contains "POST /matches verify-score section exists" "$ENDPOINTS" "verify-score"
assert_contains "verify-score two-call flow documented" "$ENDPOINTS" "pending_confirmation"
assert_contains "verify-score singles request example" "$ENDPOINTS" "winner_uid"
assert_contains "verify-score doubles request example" "$ENDPOINTS" "winner_team"
assert_contains "verify-score scoring payload documented" "$ENDPOINTS" "scoring"
assert_contains "verify-score uses snake_case p1_games (not p1Games)" "$ENDPOINTS" '"p1_games"'
assert_contains "verify-score uses snake_case winner_uid in sets (not winnerUid)" "$ENDPOINTS" '"winner_uid"'
assert_not_contains() {
  local name="$1" file="$2" pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  ✗ $name"
    echo "    forbidden pattern found: $pattern"
    echo "    file: $file"
    ((FAIL++)) || true
  else
    echo "  ✓ $name"
    ((PASS++)) || true
  fi
}
assert_not_contains "verify-score does NOT use camelCase p1Games" "$ENDPOINTS" '"p1Games"'
assert_not_contains "verify-score does NOT use camelCase winnerUid in score sets" "$ENDPOINTS" '"winnerUid"'

echo ""
echo "── spec/tab1-play-payloads.md ────────────────────────────────────────────────"

assert_contains "BROADCAST_ACTIVE doubles variant present" "$PAYLOADS" "Doubles variant\|doubles variant"
assert_contains "BROADCAST_ACTIVE doubles has match_type" "$PAYLOADS" "match_type.*doubles\|doubles.*match_type"
assert_contains "BROADCAST_ACTIVE doubles has broadcast_type find_fourth" "$PAYLOADS" "find_fourth"
assert_contains "BROADCAST_ACTIVE doubles has partner_name" "$PAYLOADS" "partner_name"
assert_contains "MATCH_SCHEDULED doubles variant with participants" "$PAYLOADS" "participants"
assert_contains "MATCH_SCHEDULED participants has team A" "$PAYLOADS" "\"team\": \"A\"\|team.*A"
assert_contains "MATCH_SCHEDULED participants has team B" "$PAYLOADS" "\"team\": \"B\"\|team.*B"
assert_contains "POST_MATCH_* doubles fields noted" "$PAYLOADS" "Doubles fields"
assert_contains "tab1-play-payloads uses server_time not serverTime" "$PAYLOADS" '"server_time"'
assert_contains "tab1-play-payloads uses broadcast_id not broadcastId" "$PAYLOADS" '"broadcast_id"'
assert_contains "tab1-play-payloads uses submitted_score not submittedScore" "$PAYLOADS" '"submitted_score"'
assert_contains "tab1-play-payloads uses p1_games not p1Games" "$PAYLOADS" '"p1_games"'

echo ""
echo "──────────────────────────────────────────────────────────────────────────────"
echo "Smoke tests PR #311: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
