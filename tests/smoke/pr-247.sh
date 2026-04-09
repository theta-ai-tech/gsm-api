#!/usr/bin/env bash
# Smoke test for PR #247 — CH-19: Seed ticker with Tab 4 event types
# Prerequisites: make emu-all (Terminal 1), make seed-emu (Terminal 2)
set -uo pipefail

BASE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"
PASS=0
FAIL=0

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

contains() { [[ "$1" == *"$2"* ]] && echo "true" || echo "false"; }

echo "=== PR #247 Smoke Tests: Ticker Seed Data ==="

# Verify emulator is reachable
if ! curl -sf http://127.0.0.1:8082/ > /dev/null 2>&1; then
  echo "FAIL: Firestore emulator not running on 127.0.0.1:8082"
  exit 1
fi
echo "OK: Firestore emulator is running"
echo ""

# Fetch all ticker documents via emulator REST API
TICKER_JSON=$(curl -sf "$BASE/ticker")

# Parse all facts with a single python call
eval "$(echo "$TICKER_JSON" | python3 -c "
import sys, json, shlex
docs = json.load(sys.stdin).get('documents', [])
types = [d['fields']['type']['stringValue'] for d in docs]
regions = [d['fields']['region']['stringValue'] for d in docs]
sports = [d['fields']['sport']['stringValue'] for d in docs]
streaks = []
directions = []
for d in docs:
    t = d['fields']['type']['stringValue']
    if t == 'win_streak':
        streaks.append(d['fields']['streak']['integerValue'])
    if t == 'tier_crossed':
        directions.append(d['fields']['direction']['stringValue'])
print(f'DOC_COUNT={len(docs)}')
print(f'UPSET_COUNT={types.count(\"upset\")}')
print(f'PB_COUNT={types.count(\"personal_best\")}')
print(f'STREAK_COUNT={types.count(\"win_streak\")}')
print(f'TIER_COUNT={types.count(\"tier_crossed\")}')
print(f'REGIONS={shlex.quote(\" \".join(sorted(set(regions))))}')
print(f'SPORTS={shlex.quote(\" \".join(sorted(set(sports))))}')
print(f'STREAKS={shlex.quote(\" \".join(str(s) for s in streaks))}')
print(f'DIRECTIONS={shlex.quote(\" \".join(directions))}')
")"

echo "1. Total ticker event count (found: $DOC_COUNT)"
check "At least 8 ticker events" "$([ "$DOC_COUNT" -ge 8 ] && echo true || echo false)"
check "Exactly 9 ticker events" "$([ "$DOC_COUNT" -eq 9 ] && echo true || echo false)"

echo ""
echo "2. Event type coverage"
check "1 upset event (found: $UPSET_COUNT)" "$([ "$UPSET_COUNT" -eq 1 ] && echo true || echo false)"
check "3 personal_best events (found: $PB_COUNT)" "$([ "$PB_COUNT" -eq 3 ] && echo true || echo false)"
check "3 win_streak events (found: $STREAK_COUNT)" "$([ "$STREAK_COUNT" -eq 3 ] && echo true || echo false)"
check "2 tier_crossed events (found: $TIER_COUNT)" "$([ "$TIER_COUNT" -eq 2 ] && echo true || echo false)"

echo ""
echo "3. Region diversity (found: $REGIONS)"
check "athens region present" "$(contains "$REGIONS" "athens")"
check "thessaloniki region present" "$(contains "$REGIONS" "thessaloniki")"
check "london region present" "$(contains "$REGIONS" "london")"

echo ""
echo "4. Sport diversity (found: $SPORTS)"
check "tennis sport present" "$(contains "$SPORTS" "tennis")"
check "padel sport present" "$(contains "$SPORTS" "padel")"
check "pickleball sport present" "$(contains "$SPORTS" "pickleball")"

echo ""
echo "5. Win streak milestones (found: $STREAKS)"
check "Streak milestone 3" "$(contains "$STREAKS" "3")"
check "Streak milestone 5" "$(contains "$STREAKS" "5")"
check "Streak milestone 10" "$(contains "$STREAKS" "10")"

echo ""
echo "6. Tier crossed directions (found: $DIRECTIONS)"
check "Promotion (up) direction" "$(contains "$DIRECTIONS" "up")"
check "Relegation (down) direction" "$(contains "$DIRECTIONS" "down")"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
