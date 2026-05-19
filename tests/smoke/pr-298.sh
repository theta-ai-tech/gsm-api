#!/usr/bin/env bash
# Smoke tests for PR #298: feat: LG-6 add standings computation to LeagueService (#253)
# Generated: 2026-05-19
# Usage: bash tests/smoke/pr-298.sh
#
# This PR introduces LeagueService.get_standings() — no HTTP endpoint yet (LG-9).
# Smoke tests exercise the unit test suite for the standings computation.
#
# Requires: venv installed (make venv && make install in main checkout).

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

echo "Smoke tests for PR #298 — LG-6 LeagueService standings computation"
echo "────────────────────────────────────────────────────────────────────"
echo ""
echo "Running unit tests for LeagueService standings..."
echo ""

PYTHON="$VENV_DIR/bin/python3"
PYTEST="$VENV_DIR/bin/pytest"

# ── Step 1: All standings unit tests pass ────────────────────────────────────
PYTHONPATH="$REPO_ROOT/api" \
  "$PYTEST" "$REPO_ROOT/tests/unit/services/test_league_service.py::TestGetStandings" -v \
    --tb=short --no-header -q 2>&1
PYTEST_EXIT=$?

assert_exit_code "LeagueService standings unit tests pass (9 tests)" 0 "$PYTEST_EXIT"

# ── Step 2: Dense ranking guard ──────────────────────────────────────────────
echo ""
echo "Verifying dense ranking: tied members share rank, next rank is +1 not +gap..."
PYTHONPATH="$REPO_ROOT/api" "$PYTHON" -c "
from unittest.mock import Mock
from datetime import datetime, timezone
from app.repos.leagues_repo import LeaguesRepo
from app.models.league import LeagueMember
from app.models.enums import LeagueRoleEnum, LeagueMemberStatusEnum
from app.services.league_service import LeagueService

repo = Mock(spec=LeaguesRepo)
repo.list_members.return_value = [
    LeagueMember(uid='uid_a', role=LeagueRoleEnum.PLAYER, status=LeagueMemberStatusEnum.ACTIVE,
                 joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc), stats={'wins': 3, 'losses': 2}),
    LeagueMember(uid='uid_b', role=LeagueRoleEnum.PLAYER, status=LeagueMemberStatusEnum.ACTIVE,
                 joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc), stats={'wins': 3, 'losses': 2}),
    LeagueMember(uid='uid_c', role=LeagueRoleEnum.PLAYER, status=LeagueMemberStatusEnum.ACTIVE,
                 joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc), stats={'wins': 1, 'losses': 0}),
]
svc = LeagueService(repo, Mock())
standings = svc.get_standings('lg1')

ranks = [e.rank for e in standings]
if ranks == [1, 1, 2]:
    print('OK: dense ranking correct [1, 1, 2]')
    exit(0)
else:
    print(f'FAIL: expected [1, 1, 2], got {ranks}')
    exit(1)
" 2>&1
DENSE_EXIT=$?
assert_exit_code "dense ranking: [3W,2L],[3W,2L],[1W,0L] → ranks [1,1,2]" 0 "$DENSE_EXIT"

# ── Step 3: Sort order guard ─────────────────────────────────────────────────
echo ""
echo "Verifying sort: wins DESC then losses ASC..."
PYTHONPATH="$REPO_ROOT/api" "$PYTHON" -c "
from unittest.mock import Mock
from datetime import datetime, timezone
from app.repos.leagues_repo import LeaguesRepo
from app.models.league import LeagueMember
from app.models.enums import LeagueRoleEnum, LeagueMemberStatusEnum
from app.services.league_service import LeagueService

repo = Mock(spec=LeaguesRepo)
repo.list_members.return_value = [
    LeagueMember(uid='low_wins', role=LeagueRoleEnum.PLAYER, status=LeagueMemberStatusEnum.ACTIVE,
                 joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc), stats={'wins': 2, 'losses': 0}),
    LeagueMember(uid='high_wins', role=LeagueRoleEnum.PLAYER, status=LeagueMemberStatusEnum.ACTIVE,
                 joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc), stats={'wins': 5, 'losses': 0}),
]
svc = LeagueService(repo, Mock())
standings = svc.get_standings('lg1')

if standings[0].uid == 'high_wins' and standings[0].rank == 1:
    print('OK: highest wins ranked first')
    exit(0)
else:
    print(f'FAIL: expected high_wins rank 1, got uid={standings[0].uid} rank={standings[0].rank}')
    exit(1)
" 2>&1
SORT_EXIT=$?
assert_exit_code "sort order: highest wins ranked first" 0 "$SORT_EXIT"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #298: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
