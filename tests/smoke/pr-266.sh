#!/usr/bin/env bash
# Smoke test for PR #266 — VEN-3: Seed Athens padel + tennis venues
# Requires Firestore emulator running on 127.0.0.1:8082
# Run from the gsm-api root: bash tests/smoke/pr-266.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PASS=0
FAIL=0

EMU_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
BASE_URL="http://${EMU_HOST}/v1/projects/${PROJECT}/databases/(default)/documents"

check() {
  local desc="$1" result="$2"
  if [ "$result" = "true" ]; then
    echo "  PASS: $desc"
    ((PASS++))
  else
    echo "  FAIL: $desc"
    ((FAIL++))
  fi
}

echo "=== PR #266 Smoke Tests: Seed Athens Venues ==="
echo ""

# --- Pre-flight: emulator reachable ---
echo "--- Pre-flight ---"
EMU_UP=$(curl -sf "http://${EMU_HOST}/" -o /dev/null && echo true || echo true)
# Emulator returns 404 on root but that's fine; we just need TCP connectivity
EMU_TCP=$(curl -sf --max-time 2 "${BASE_URL}/venues" -o /dev/null 2>&1; [ $? -le 22 ] && echo true || echo false)
check "Firestore emulator reachable at ${EMU_HOST}" "$EMU_TCP"

if [ "$EMU_TCP" != "true" ]; then
  echo ""
  echo "ABORT: Firestore emulator not reachable. Start it with: make emu-firestore"
  exit 1
fi

# --- Seed ---
echo ""
echo "--- Seeding ---"
export FIRESTORE_EMULATOR_HOST="$EMU_HOST"
export GOOGLE_CLOUD_PROJECT="$PROJECT"
SEED_OUTPUT=$( cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" .venv/bin/python -m tools.seed_firestore --env=emu 2>&1 )
SEED_OK=$( echo "$SEED_OUTPUT" | grep -q "venues" && echo true || echo false )
check "make seed-emu succeeds and mentions venues" "$SEED_OK"

# --- Venue count ---
echo ""
echo "--- Venue count ---"
VENUES_JSON=$(curl -sf "${BASE_URL}/venues" 2>/dev/null)
DOC_COUNT=$(echo "$VENUES_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('documents',[])))" 2>/dev/null)
check "16 venue documents seeded" "$([ "$DOC_COUNT" = "16" ] && echo true || echo false)"

# --- Spot-check: Ten Twenty Club ---
echo ""
echo "--- Spot-check: Ten Twenty Club ---"
TTC_JSON=$(curl -sf "${BASE_URL}/venues/ten_twenty_club" 2>/dev/null)
TTC_NAME=$(echo "$TTC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin).get('fields',{}); print(d.get('name',{}).get('stringValue',''))" 2>/dev/null)
check "ten_twenty_club name = 'Ten Twenty Club'" "$([ "$TTC_NAME" = "Ten Twenty Club" ] && echo true || echo false)"

TTC_AREA=$(echo "$TTC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin).get('fields',{}); print(d.get('area',{}).get('stringValue',''))" 2>/dev/null)
check "ten_twenty_club area = 'Voula'" "$([ "$TTC_AREA" = "Voula" ] && echo true || echo false)"

TTC_SPORT=$(echo "$TTC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin).get('fields',{}); vals=d.get('sports',{}).get('arrayValue',{}).get('values',[]); print(vals[0].get('stringValue','') if vals else '')" 2>/dev/null)
check "ten_twenty_club sport = 'padel'" "$([ "$TTC_SPORT" = "padel" ] && echo true || echo false)"

# --- Spot-check: Athens Tennis Club ---
echo ""
echo "--- Spot-check: Athens Tennis Club ---"
ATC_JSON=$(curl -sf "${BASE_URL}/venues/athens_tennis_club" 2>/dev/null)
ATC_NAME=$(echo "$ATC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin).get('fields',{}); print(d.get('name',{}).get('stringValue',''))" 2>/dev/null)
check "athens_tennis_club name = 'Athens Tennis Club'" "$([ "$ATC_NAME" = "Athens Tennis Club" ] && echo true || echo false)"

ATC_SPORT=$(echo "$ATC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin).get('fields',{}); vals=d.get('sports',{}).get('arrayValue',{}).get('values',[]); print(vals[0].get('stringValue','') if vals else '')" 2>/dev/null)
check "athens_tennis_club sport = 'tennis'" "$([ "$ATC_SPORT" = "tennis" ] && echo true || echo false)"

# --- Spot-check: multi-sport venue ---
echo ""
echo "--- Spot-check: Voula Sports Complex (multi-sport) ---"
VSC_JSON=$(curl -sf "${BASE_URL}/venues/voula_sports_complex" 2>/dev/null)
VSC_SPORTS=$(echo "$VSC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin).get('fields',{}); vals=d.get('sports',{}).get('arrayValue',{}).get('values',[]); print(len(vals))" 2>/dev/null)
check "voula_sports_complex has 2 sports" "$([ "$VSC_SPORTS" = "2" ] && echo true || echo false)"

# --- Summary ---
echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
