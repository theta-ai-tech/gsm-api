#!/usr/bin/env bash
# Smoke tests for PR #294: feat: LG-2 add LeagueBrowseCard Pydantic model and mapper (#249)
# Generated: 2026-05-17
# Usage: bash tests/smoke/pr-294.sh
#
# Requires: Firestore emulator running at 127.0.0.1:8082 (make emu-all).
# No API server needed — this PR is model/mapper layer only; tests run via
# Firestore emulator REST API and direct Python import checks.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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

assert_not_empty() {
  local name="$1" actual="$2"
  if [ -n "$actual" ] && [ "$actual" != "null" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (got empty/null)"
    ((FAIL++)) || true
  fi
}

# ── Preflight: Firestore emulator ────────────────────────────────────────────
echo "Preflight: checking Firestore emulator at 127.0.0.1:8082..."
if ! curl -fsS "$FIRESTORE/" >/dev/null 2>&1; then
  echo "ABORT: Firestore emulator not reachable. Run 'make emu-all' first."
  exit 1
fi
echo "  emulator OK"
echo ""

# ── Test 1: create a test league doc with LG-1 browse fields and verify ──────
echo "Test 1: Firestore PATCH + GET league doc with LG-1 browse fields"
curl -s -X PATCH "$FIRESTORE/leagues/smoke_lg2_test?currentDocument.exists=false" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "sport":          {"stringValue": "tennis"},
      "status":         {"stringValue": "open"},
      "name":           {"stringValue": "Smoke Test League"},
      "region":         {"stringValue": "Madrid"},
      "maxPlayers":     {"integerValue": "16"},
      "currentPlayers": {"integerValue": "4"},
      "tier":           {"stringValue": "amateur"},
      "startDate":      {"stringValue": "2026-06-01T00:00:00Z"}
    }
  }' > /dev/null 2>&1

# Also allow update if doc already exists (re-run idempotency)
curl -s -X PATCH "$FIRESTORE/leagues/smoke_lg2_test" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "sport":          {"stringValue": "tennis"},
      "status":         {"stringValue": "open"},
      "name":           {"stringValue": "Smoke Test League"},
      "region":         {"stringValue": "Madrid"},
      "maxPlayers":     {"integerValue": "16"},
      "currentPlayers": {"integerValue": "4"},
      "tier":           {"stringValue": "amateur"},
      "startDate":      {"stringValue": "2026-06-01T00:00:00Z"}
    }
  }' > /dev/null 2>&1

DOC=$(curl -s "$FIRESTORE/leagues/smoke_lg2_test")
SPORT=$(echo "$DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('sport',{}).get('stringValue','null'))" 2>/dev/null || echo "null")
STATUS=$(echo "$DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('status',{}).get('stringValue','null'))" 2>/dev/null || echo "null")
REGION=$(echo "$DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('region',{}).get('stringValue','null'))" 2>/dev/null || echo "null")
assert_eq "smoke_lg2_test.sport = tennis" "$SPORT" "tennis"
assert_eq "smoke_lg2_test.status = open" "$STATUS" "open"
assert_eq "smoke_lg2_test.region = Madrid" "$REGION" "Madrid"

# ── Test 2: LeagueBrowseCard model is importable ─────────────────────────────
echo ""
echo "Test 2: LeagueBrowseCard is importable from app.models"
IMPORT_RESULT=$("$VENV_DIR/bin/python" -c "
from app.models import LeagueBrowseCard
print('ok')
" 2>&1)
assert_eq "LeagueBrowseCard importable" "$IMPORT_RESULT" "ok"

# ── Test 3: to_league_browse_card mapper runs correctly ──────────────────────
echo ""
echo "Test 3: to_league_browse_card() maps a full doc correctly"
MAPPER_RESULT=$("$VENV_DIR/bin/python" -c "
from app.models import LeagueBrowseCard
from app.repos.mappers import to_league_browse_card
doc = {
    'sport': 'tennis',
    'status': 'open',
    'name': 'Test League',
    'region': 'Madrid',
    'maxPlayers': 16,
    'currentPlayers': 4,
    'tier': 'amateur',
}
card = to_league_browse_card(doc, league_id='league_open')
assert card.league_id == 'league_open', f'league_id mismatch: {card.league_id}'
assert card.sport.value == 'tennis', f'sport mismatch: {card.sport}'
assert card.status.value == 'open', f'status mismatch: {card.status}'
assert card.region == 'Madrid', f'region mismatch: {card.region}'
assert card.max_players == 16, f'max_players mismatch: {card.max_players}'
assert card.current_players == 4, f'current_players mismatch: {card.current_players}'
assert card.tier == 'amateur', f'tier mismatch: {card.tier}'
assert card.start_date is None, f'start_date should be None: {card.start_date}'
print('ok')
" 2>&1)
assert_eq "to_league_browse_card full doc" "$MAPPER_RESULT" "ok"

# ── Test 4: minimal doc (backward compat) ────────────────────────────────────
echo ""
echo "Test 4: to_league_browse_card() handles minimal/legacy doc"
MINIMAL_RESULT=$("$VENV_DIR/bin/python" -c "
from app.repos.mappers import to_league_browse_card
doc = {'sport': 'tennis', 'status': 'active', 'name': 'Legacy League'}
card = to_league_browse_card(doc, league_id='legacy_league')
assert card.region is None, f'region should be None: {card.region}'
assert card.max_players is None, f'max_players should be None: {card.max_players}'
assert card.current_players is None, f'current_players should be None: {card.current_players}'
assert card.tier is None, f'tier should be None: {card.tier}'
assert card.start_date is None, f'start_date should be None: {card.start_date}'
print('ok')
" 2>&1)
assert_eq "to_league_browse_card legacy doc (all optionals None)" "$MINIMAL_RESULT" "ok"

# ── Test 5: LeagueBrowseCard in __all__ ──────────────────────────────────────
echo ""
echo "Test 5: LeagueBrowseCard is in app.models.__all__"
ALL_RESULT=$("$VENV_DIR/bin/python" -c "
import app.models as m
print('ok' if 'LeagueBrowseCard' in m.__all__ else 'missing')
" 2>&1)
assert_eq "LeagueBrowseCard in __all__" "$ALL_RESULT" "ok"

# ── Teardown ────────────────────────────────────────────────────────────────
curl -s -X DELETE "$FIRESTORE/leagues/smoke_lg2_test" > /dev/null 2>&1

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #294: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
