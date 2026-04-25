#!/usr/bin/env bash
# Smoke test for PR #281 — DBL-1: doubles enums + ParticipantEntry model
#
# This PR adds models only (no HTTP endpoints, no Firestore reads/writes).
# The smoke test exercises the new symbols directly via the Python REPL inside
# the active venv to validate enum values, StrEnum identity, and
# ParticipantEntry validation in both singles and doubles cases.
#
# Prerequisites:
#   The repo's venv must be installed: `make venv && make install` from repo root.
#   Emulators are NOT required for this script — there is no I/O.
#
# Run from the gsm-api root: bash tests/smoke/pr-281.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
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

echo "=== PR #281 Smoke Tests: DBL-1 doubles enums + ParticipantEntry ==="
echo ""

# --- Pre-flight: venv exists ---
echo "--- Pre-flight ---"
VENV_OK=$([ -f "$REPO_ROOT/.venv/bin/activate" ] && echo true || echo false)
check "Virtualenv exists at $REPO_ROOT/.venv" "$VENV_OK"

if [ "$VENV_OK" != "true" ]; then
  echo ""
  echo "ABORT: venv not found. Run: make venv && make install"
  exit 1
fi

# --- Test 1: Imports succeed ---
echo ""
echo "--- Import tests ---"
IMPORT_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import BroadcastTypeEnum, MatchTypeEnum, ParticipantEntry
print('true')
" 2>/dev/null || echo false)
check "from app.models import MatchTypeEnum, BroadcastTypeEnum, ParticipantEntry" "$IMPORT_OK"

if [ "$IMPORT_OK" != "true" ]; then
  echo ""
  echo "ABORT: Imports failed."
  exit 1
fi

# --- Test 2: MatchTypeEnum values ---
echo ""
echo "--- MatchTypeEnum tests ---"
MT_VALUES_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import MatchTypeEnum
ok = (
    MatchTypeEnum.SINGLES == 'singles'
    and MatchTypeEnum.DOUBLES == 'doubles'
    and len(MatchTypeEnum) == 2
)
print('true' if ok else 'false')
" 2>/dev/null || echo false)
check "MatchTypeEnum has SINGLES='singles', DOUBLES='doubles', len==2" "$MT_VALUES_OK"

MT_STR_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import MatchTypeEnum
print('true' if isinstance(MatchTypeEnum.SINGLES, str) and isinstance(MatchTypeEnum.DOUBLES, str) else 'false')
" 2>/dev/null || echo false)
check "MatchTypeEnum members are str instances (StrEnum)" "$MT_STR_OK"

MT_ROUND_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import MatchTypeEnum
ok = (
    MatchTypeEnum('singles') is MatchTypeEnum.SINGLES
    and MatchTypeEnum('doubles') is MatchTypeEnum.DOUBLES
)
print('true' if ok else 'false')
" 2>/dev/null || echo false)
check "MatchTypeEnum string round-trip" "$MT_ROUND_OK"

# --- Test 3: BroadcastTypeEnum values ---
echo ""
echo "--- BroadcastTypeEnum tests ---"
BT_VALUES_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import BroadcastTypeEnum
ok = (
    BroadcastTypeEnum.FIND_OPPONENT == 'find_opponent'
    and BroadcastTypeEnum.FIND_FOURTH == 'find_fourth'
    and len(BroadcastTypeEnum) == 2
)
print('true' if ok else 'false')
" 2>/dev/null || echo false)
check "BroadcastTypeEnum has FIND_OPPONENT='find_opponent', FIND_FOURTH='find_fourth', len==2" "$BT_VALUES_OK"

BT_STR_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import BroadcastTypeEnum
print('true' if isinstance(BroadcastTypeEnum.FIND_OPPONENT, str) and isinstance(BroadcastTypeEnum.FIND_FOURTH, str) else 'false')
" 2>/dev/null || echo false)
check "BroadcastTypeEnum members are str instances (StrEnum)" "$BT_STR_OK"

BT_ROUND_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import BroadcastTypeEnum
ok = (
    BroadcastTypeEnum('find_opponent') is BroadcastTypeEnum.FIND_OPPONENT
    and BroadcastTypeEnum('find_fourth') is BroadcastTypeEnum.FIND_FOURTH
)
print('true' if ok else 'false')
" 2>/dev/null || echo false)
check "BroadcastTypeEnum string round-trip" "$BT_ROUND_OK"

# --- Test 4: ParticipantEntry singles (team=None) is valid ---
echo ""
echo "--- ParticipantEntry singles case ---"
SINGLES_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
p = ParticipantEntry(uid='user_ignatios', team=None, display_name='Ignatios C')
print('true' if p.uid == 'user_ignatios' and p.team is None and p.display_name == 'Ignatios C' else 'false')
" 2>/dev/null || echo false)
check "ParticipantEntry(team=None) is valid (singles)" "$SINGLES_OK"

# --- Test 5: ParticipantEntry doubles team='A' is valid ---
echo ""
echo "--- ParticipantEntry doubles case ---"
DOUBLES_A_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
p = ParticipantEntry(uid='user_ignatios', team='A', display_name='Ignatios C')
print('true' if p.team == 'A' else 'false')
" 2>/dev/null || echo false)
check "ParticipantEntry(team='A') is valid (doubles)" "$DOUBLES_A_OK"

DOUBLES_B_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
p = ParticipantEntry(uid='user_ignatios', team='B', display_name='Ignatios C')
print('true' if p.team == 'B' else 'false')
" 2>/dev/null || echo false)
check "ParticipantEntry(team='B') is valid (doubles)" "$DOUBLES_B_OK"

# --- Test 6: Invalid team values rejected ---
echo ""
echo "--- ParticipantEntry validation tests ---"
INVALID_TEAM_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
from pydantic import ValidationError
try:
    ParticipantEntry(uid='user_ignatios', team='C', display_name='Ignatios C')
    print('false')
except ValidationError:
    print('true')
" 2>/dev/null || echo false)
check "ParticipantEntry(team='C') raises ValidationError" "$INVALID_TEAM_OK"

EMPTY_UID_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
from pydantic import ValidationError
try:
    ParticipantEntry(uid='', team=None, display_name='Ignatios C')
    print('false')
except ValidationError:
    print('true')
" 2>/dev/null || echo false)
check "ParticipantEntry(uid='') raises ValidationError (min_length)" "$EMPTY_UID_OK"

EMPTY_DISPLAY_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
from pydantic import ValidationError
try:
    ParticipantEntry(uid='user_ignatios', team=None, display_name='')
    print('false')
except ValidationError:
    print('true')
" 2>/dev/null || echo false)
check "ParticipantEntry(display_name='') raises ValidationError (min_length)" "$EMPTY_DISPLAY_OK"

# --- Test 7: by_alias serialization (camelCase for Firestore) ---
echo ""
echo "--- ParticipantEntry serialization ---"
ALIAS_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
p = ParticipantEntry(uid='u1', team='A', display_name='Alex K')
d = p.model_dump(by_alias=True)
ok = d.get('uid') == 'u1' and d.get('team') == 'A' and d.get('displayName') == 'Alex K'
print('true' if ok else 'false')
" 2>/dev/null || echo false)
check "model_dump(by_alias=True) emits camelCase 'displayName'" "$ALIAS_OK"

SNAKE_OK=$(cd "$REPO_ROOT" && . .venv/bin/activate && python3 -c "
from app.models import ParticipantEntry
p = ParticipantEntry(uid='u1', team='A', display_name='Alex K')
d = p.model_dump()
ok = d.get('uid') == 'u1' and d.get('team') == 'A' and d.get('display_name') == 'Alex K'
print('true' if ok else 'false')
" 2>/dev/null || echo false)
check "model_dump() (no alias) emits snake_case 'display_name'" "$SNAKE_OK"

# --- Test 8: Unit tests for the new models pass ---
echo ""
echo "--- Unit test verification ---"
cd "$REPO_ROOT"
UNIT_OUTPUT=$(. .venv/bin/activate && \
  pytest tests/unit/models/test_doubles_enums.py tests/unit/models/test_common.py -q 2>&1)
UNIT_OK=$(echo "$UNIT_OUTPUT" | grep -q "passed" && echo true || echo false)
check "Unit tests for doubles enums and common models pass" "$UNIT_OK"

# --- Summary ---
echo ""
echo "==============================="
echo "  PASS: $PASS    FAIL: $FAIL"
echo "==============================="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
