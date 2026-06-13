#!/usr/bin/env bash
# Smoke tests for PR #295: feat: LG-3 declare composite Firestore indexes for leagues browse (#250)
# Generated: 2026-05-17
# Usage: bash tests/smoke/pr-295.sh
#
# LG-3 is config+docs only — it declares composite Firestore indexes in
# firestore.indexes.json. The Firestore emulator does NOT enforce composite
# index declarations, so this script verifies:
#   1. Both required index entries are present in firestore.indexes.json
#   2. A league document is readable from the emulator (data layer sanity)
#
# Requires: make emu-all running + seed loaded.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected to contain: $needle"
    ((FAIL++)) || true
  fi
}

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="${MAIN_WT:-$REPO_ROOT}/.venv"
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# ── Seed the emulator ───────────────────────────────────────────────────────
echo "Seeding emulator..."
(cd "$REPO_ROOT" && . "$VENV_DIR/bin/activate" && \
  FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}" \
  GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}" \
  python3 tools/seed_data.py) > /dev/null 2>&1

# ── Tests — verify index declarations in firestore.indexes.json ─────────────
echo ""
echo "── firestore.indexes.json — leagues composite indexes ───────────────────"

INDEXES_FILE="$REPO_ROOT/firestore.indexes.json"

# Extract all leagues index entries as a block for inspection
LEAGUES_INDEXES=$(python3 -c "
import json, sys
with open('$INDEXES_FILE') as f:
    # Strip comments by reading line-by-line and filtering '//' lines
    lines = [l for l in f.readlines() if not l.strip().startswith('//')]
    data = json.loads(''.join(lines))
leagues = [idx for idx in data['indexes'] if idx.get('collectionGroup') == 'leagues']
print(json.dumps(leagues, indent=2))
" 2>/dev/null)

# Check primary index: region + sport + status
PRIMARY=$(echo "$LEAGUES_INDEXES" | python3 -c "
import json, sys
indexes = json.load(sys.stdin)
target = [
    {'fieldPath': 'region', 'mode': 'ASCENDING'},
    {'fieldPath': 'sport', 'mode': 'ASCENDING'},
    {'fieldPath': 'status', 'mode': 'ASCENDING'},
]
found = any(idx.get('fields') == target for idx in indexes)
print('yes' if found else 'no')
")
assert_eq "primary index (region, sport, status)" "$PRIMARY" "yes"

# Check secondary index: region + sport + status + startDate
SECONDARY=$(echo "$LEAGUES_INDEXES" | python3 -c "
import json, sys
indexes = json.load(sys.stdin)
target = [
    {'fieldPath': 'region', 'mode': 'ASCENDING'},
    {'fieldPath': 'sport', 'mode': 'ASCENDING'},
    {'fieldPath': 'status', 'mode': 'ASCENDING'},
    {'fieldPath': 'startDate', 'mode': 'ASCENDING'},
]
found = any(idx.get('fields') == target for idx in indexes)
print('yes' if found else 'no')
")
assert_eq "secondary index (region, sport, status, startDate)" "$SECONDARY" "yes"

# Check both indexes have queryScope=COLLECTION
SCOPE_OK=$(echo "$LEAGUES_INDEXES" | python3 -c "
import json, sys
indexes = json.load(sys.stdin)
all_ok = all(idx.get('queryScope') == 'COLLECTION' for idx in indexes)
print('yes' if all_ok else 'no')
")
assert_eq "all leagues indexes have queryScope=COLLECTION" "$SCOPE_OK" "yes"

# ── Tests — DATA_DICTIONARY.md has required composite indexes section ────────
echo ""
echo "── wiki/DATA_DICTIONARY.md — leagues indexes documentation ─────────────"

DICT_FILE="$REPO_ROOT/wiki/DATA_DICTIONARY.md"
LEAGUES_BLOCK=$(awk '/^## Collection: leagues/,/^## Collection: courts/' "$DICT_FILE")

assert_contains "leagues section has Required composite indexes heading" \
  "$LEAGUES_BLOCK" "### Required composite indexes"

assert_contains "leagues section documents primary index" \
  "$LEAGUES_BLOCK" "region"

assert_contains "leagues section has deployment note" \
  "$LEAGUES_BLOCK" "firebase deploy --only firestore:indexes"

# ── Tests — emulator data layer sanity (league doc readable) ─────────────────
echo ""
echo "── Firestore emulator — league document read ────────────────────────────"

PADEL=$(curl -s "$FIRESTORE/leagues/padel-local-2025")
LEAGUE_NAME=$(echo "$PADEL" | jq -r '.fields.name.stringValue // "null"')
assert_eq "padel-local-2025 league doc is readable from emulator" \
  "$LEAGUE_NAME" "Local Padel Ladder 2025"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #295: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
