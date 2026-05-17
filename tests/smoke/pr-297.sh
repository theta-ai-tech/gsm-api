#!/usr/bin/env bash
# Smoke tests for PR #297: feat: LG-5 create LeagueService — join flow with capacity, duplicate, status checks (#252)
# Generated: 2026-05-17
# Usage: bash tests/smoke/pr-297.sh
#
# This PR introduces LeagueService (no HTTP endpoint yet — that is LG-10).
# Smoke tests exercise the unit test suite for the service layer.
#
# Requires: Firestore emulator running (make emu-all) and venv installed.

set -uo pipefail

PASS=0
FAIL=0

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2 ; exit}')
  VENV_DIR="${MAIN_WT}/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
  exit 1
fi

# ── Helpers ─────────────────────────────────────────────────────────────────
assert_exit_code() {
  local name="$1" expected="$2" actual="$3"
  if [ "$actual" -eq "$expected" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name (exit $actual, expected $expected)"
    ((FAIL++)) || true
  fi
}

echo "Smoke tests for PR #297 — LG-5 LeagueService join flow"
echo "────────────────────────────────────────────────────────"
echo ""
echo "Running unit tests for LeagueService..."
echo ""

PYTHON="$VENV_DIR/bin/python3"
PYTEST="$VENV_DIR/bin/pytest"

# ── Step 1: All LeagueService unit tests pass ────────────────────────────────
PYTHONPATH="$REPO_ROOT/api" \
  "$PYTEST" "$REPO_ROOT/tests/unit/services/test_league_service.py" -v \
    --tb=short --no-header -q 2>&1
PYTEST_EXIT=$?

assert_exit_code "LeagueService unit tests pass (9 tests)" 0 "$PYTEST_EXIT"

# ── Step 2: Not-found guard raises ──────────────────────────────────────────
echo ""
echo "Verifying specific guard: league not found..."
PYTHONPATH="$REPO_ROOT/api" "$PYTHON" -c "
from unittest.mock import Mock
from app.repos.leagues_repo import LeaguesRepo
from app.services.league_service import LeagueService

repo = Mock(spec=LeaguesRepo)
repo.get_by_id.return_value = None
svc = LeagueService(repo, Mock())

try:
    svc.join_league('nonexistent', 'uid1')
    print('FAIL: expected ValueError')
    exit(1)
except ValueError as e:
    if 'not found' in str(e):
        print('OK: raises ValueError with not found')
        exit(0)
    print(f'FAIL: unexpected message: {e}')
    exit(1)
" 2>&1
GUARD_EXIT=$?
assert_exit_code "not-found guard raises ValueError" 0 "$GUARD_EXIT"

# ── Step 3: Full capacity guard raises ──────────────────────────────────────
echo ""
echo "Verifying specific guard: full capacity..."
PYTHONPATH="$REPO_ROOT/api" "$PYTHON" -c "
from unittest.mock import Mock
from app.repos.leagues_repo import LeaguesRepo
from app.models.league import League
from app.models.enums import LeagueStatusEnum, SportEnum
from app.services.league_service import LeagueService

repo = Mock(spec=LeaguesRepo)
repo.get_by_id.return_value = League(
    league_id='lg1', name='Full League', sport=SportEnum.TENNIS,
    status=LeagueStatusEnum.OPEN, owner_uid='o1', max_players=5, current_players=5,
)
repo.list_members.return_value = []
svc = LeagueService(repo, Mock())

try:
    svc.join_league('lg1', 'uid1')
    print('FAIL: expected ValueError')
    exit(1)
except ValueError as e:
    if 'full capacity' in str(e):
        print('OK: raises ValueError with full capacity')
        exit(0)
    print(f'FAIL: unexpected message: {e}')
    exit(1)
" 2>&1
CAP_EXIT=$?
assert_exit_code "full-capacity guard raises ValueError" 0 "$CAP_EXIT"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #297: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
