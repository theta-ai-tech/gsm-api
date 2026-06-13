#!/usr/bin/env bash
# Smoke tests for PR #296: feat: LG-4 extend LeaguesRepo with list_by_filter, get_member_count, increment_member_count (#251)
# Generated: 2026-05-17
# Usage: bash tests/smoke/pr-296.sh
#
# Requires: make emu-all running (Firestore + Auth emulators).
# No HTTP endpoints are added in this PR — tests verify the Firestore emulator
# has the expected seeded league data and that the new repo unit tests pass.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ──────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree / {print $2; exit}')
  VENV_DIR="${MAIN_WT}/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# ── Helpers ──────────────────────────────────────────────────────────────────

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

# ── Preflight: Firestore emulator ────────────────────────────────────────────
echo "Preflight: checking Firestore emulator..."
if ! curl -fsS "http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents/" > /dev/null 2>&1; then
  echo "ERROR: Firestore emulator not reachable at 127.0.0.1:8082. Run 'make emu-all'."
  exit 1
fi
echo "  ✓ Firestore emulator is up"

# ── Test group 1: Seeded league data in Firestore emulator ───────────────────
echo ""
echo "Group 1: Verify seeded league data (padel-local-2025)"

LEAGUE_DOC=$(curl -s "$FIRESTORE/leagues/padel-local-2025")

REGION=$(echo "$LEAGUE_DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('region',{}).get('stringValue','null'))")
assert_eq "padel-local-2025 region = athens" "$REGION" "athens"

SPORT=$(echo "$LEAGUE_DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('sport',{}).get('stringValue','null'))")
assert_eq "padel-local-2025 sport = padel" "$SPORT" "padel"

STATUS=$(echo "$LEAGUE_DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('status',{}).get('stringValue','null'))")
assert_eq "padel-local-2025 status = active" "$STATUS" "active"

CURRENT_PLAYERS=$(echo "$LEAGUE_DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('currentPlayers',{}).get('integerValue','null'))")
assert_eq "padel-local-2025 currentPlayers = 3" "$CURRENT_PLAYERS" "3"

# ── Test group 2: Second seeded league (tennis-local-2025) ───────────────────
echo ""
echo "Group 2: Verify seeded league data (tennis-local-2025)"

TENNIS_DOC=$(curl -s "$FIRESTORE/leagues/tennis-local-2025")

TENNIS_SPORT=$(echo "$TENNIS_DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('sport',{}).get('stringValue','null'))")
assert_eq "tennis-local-2025 sport = tennis" "$TENNIS_SPORT" "tennis"

TENNIS_STATUS=$(echo "$TENNIS_DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('status',{}).get('stringValue','null'))")
assert_eq "tennis-local-2025 status = open" "$TENNIS_STATUS" "open"

TENNIS_REGION=$(echo "$TENNIS_DOC" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fields',{}).get('region',{}).get('stringValue','null'))")
assert_eq "tennis-local-2025 region = thessaloniki" "$TENNIS_REGION" "thessaloniki"

# ── Test group 3: New unit tests pass ────────────────────────────────────────
echo ""
echo "Group 3: Run new LeaguesRepo unit tests"

if . "$VENV_DIR/bin/activate" && \
   python3 -m pytest "$REPO_ROOT/tests/unit/repos/test_leagues_repo.py" -q --tb=short 2>&1 | tail -5 | grep -q "passed"; then
  echo "  ✓ LeaguesRepo unit tests pass"
  ((PASS++)) || true
else
  echo "  ✗ LeaguesRepo unit tests failed"
  . "$VENV_DIR/bin/activate" && python3 -m pytest "$REPO_ROOT/tests/unit/repos/test_leagues_repo.py" -v --tb=short 2>&1 | tail -20
  ((FAIL++)) || true
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #296: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
