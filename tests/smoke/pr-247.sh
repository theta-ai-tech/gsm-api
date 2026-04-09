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

# Parse all facts with a single python call — streaks as a JSON array for exact matching
eval "$(echo "$TICKER_JSON" | python3 -c "
import sys, json, shlex
docs = json.load(sys.stdin).get('documents', [])
types = [d['fields']['type']['stringValue'] for d in docs]
regions = set(d['fields']['region']['stringValue'] for d in docs)
sports = set(d['fields']['sport']['stringValue'] for d in docs)
streaks = set()
directions = set()
for d in docs:
    t = d['fields']['type']['stringValue']
    if t == 'win_streak':
        streaks.add(int(d['fields']['streak']['integerValue']))
    if t == 'tier_crossed':
        directions.add(d['fields']['direction']['stringValue'])
print(f'DOC_COUNT={len(docs)}')
print(f'UPSET_COUNT={types.count(\"upset\")}')
print(f'PB_COUNT={types.count(\"personal_best\")}')
print(f'STREAK_COUNT={types.count(\"win_streak\")}')
print(f'TIER_COUNT={types.count(\"tier_crossed\")}')
print(f'HAS_ATHENS={shlex.quote(str(\"athens\" in regions).lower())}')
print(f'HAS_THESSALONIKI={shlex.quote(str(\"thessaloniki\" in regions).lower())}')
print(f'HAS_LONDON={shlex.quote(str(\"london\" in regions).lower())}')
print(f'HAS_TENNIS={shlex.quote(str(\"tennis\" in sports).lower())}')
print(f'HAS_PADEL={shlex.quote(str(\"padel\" in sports).lower())}')
print(f'HAS_PICKLEBALL={shlex.quote(str(\"pickleball\" in sports).lower())}')
print(f'HAS_STREAK_3={shlex.quote(str(3 in streaks).lower())}')
print(f'HAS_STREAK_5={shlex.quote(str(5 in streaks).lower())}')
print(f'HAS_STREAK_10={shlex.quote(str(10 in streaks).lower())}')
print(f'HAS_STREAK_20={shlex.quote(str(20 in streaks).lower())}')
print(f'HAS_DIR_UP={shlex.quote(str(\"up\" in directions).lower())}')
print(f'HAS_DIR_DOWN={shlex.quote(str(\"down\" in directions).lower())}')
print(f'REGIONS={shlex.quote(\" \".join(sorted(regions)))}')
print(f'SPORTS={shlex.quote(\" \".join(sorted(sports)))}')
print(f'STREAKS={shlex.quote(\" \".join(str(s) for s in sorted(streaks)))}')
")"

echo "1. Total ticker event count (found: $DOC_COUNT)"
check "At least 8 ticker events" "$([ "$DOC_COUNT" -ge 8 ] && echo true || echo false)"
check "Exactly 10 ticker events" "$([ "$DOC_COUNT" -eq 10 ] && echo true || echo false)"

echo ""
echo "2. Event type coverage"
check "1 upset event (found: $UPSET_COUNT)" "$([ "$UPSET_COUNT" -eq 1 ] && echo true || echo false)"
check "3 personal_best events (found: $PB_COUNT)" \
  "$([ "$PB_COUNT" -eq 3 ] && echo true || echo false)"
check "4 win_streak events (found: $STREAK_COUNT)" \
  "$([ "$STREAK_COUNT" -eq 4 ] && echo true || echo false)"
check "2 tier_crossed events (found: $TIER_COUNT)" \
  "$([ "$TIER_COUNT" -eq 2 ] && echo true || echo false)"

echo ""
echo "3. Region diversity (found: $REGIONS)"
check "athens region present" "$HAS_ATHENS"
check "thessaloniki region present" "$HAS_THESSALONIKI"
check "london region present" "$HAS_LONDON"

echo ""
echo "4. Sport diversity (found: $SPORTS)"
check "tennis sport present" "$HAS_TENNIS"
check "padel sport present" "$HAS_PADEL"
check "pickleball sport present" "$HAS_PICKLEBALL"

echo ""
echo "5. Win streak milestones (found: $STREAKS)"
check "Streak milestone 3" "$HAS_STREAK_3"
check "Streak milestone 5" "$HAS_STREAK_5"
check "Streak milestone 10" "$HAS_STREAK_10"
check "Streak milestone 20" "$HAS_STREAK_20"

echo ""
echo "6. Tier crossed directions"
check "Promotion (up) direction" "$HAS_DIR_UP"
check "Relegation (down) direction" "$HAS_DIR_DOWN"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
