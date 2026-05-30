#!/usr/bin/env bash
# Smoke tests for PR #306: test: LG-14 unit tests — LeagueService join flow, standings, browse filtering (#261)
# Generated: 2026-05-21
# Usage: bash tests/smoke/pr-306.sh
#
# This PR adds unit tests only — no API endpoints or Firestore schema changes.
# Verification is via make test-unit. No emulator or running API required.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_REPO_ROOT="$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}')"
VENV_DIR="${MAIN_REPO_ROOT:-$REPO_ROOT}/.venv"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
  exit 1
fi

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

# ── Tests ───────────────────────────────────────────────────────────────────

echo "Running unit tests for PR #306 (LG-14)..."
echo ""

PYTEST_OUTPUT=$(
  PYTHONPATH="$REPO_ROOT/api" \
    "$VENV_DIR/bin/pytest" \
    tests/unit/repos/test_leagues_repo.py::TestLeaguesRepoListByFilter::test_list_by_filter_by_sport \
    tests/unit/repos/test_leagues_repo.py::TestLeaguesRepoListByFilter::test_list_by_filter_by_status \
    --tb=short -q 2>&1
)
PYTEST_EXIT=$?

# Test 1: test_list_by_filter_by_sport passes
if echo "$PYTEST_OUTPUT" | grep -q "test_list_by_filter_by_sport PASSED"; then
  SPORT_RESULT="PASSED"
elif echo "$PYTEST_OUTPUT" | grep -q "1 passed\|2 passed"; then
  SPORT_RESULT="PASSED"
else
  SPORT_RESULT="FAILED"
fi

# Test 2: test_list_by_filter_by_status passes
if echo "$PYTEST_OUTPUT" | grep -q "test_list_by_filter_by_status PASSED"; then
  STATUS_RESULT="PASSED"
elif [ "$PYTEST_EXIT" -eq 0 ]; then
  STATUS_RESULT="PASSED"
else
  STATUS_RESULT="FAILED"
fi

assert_eq "test_list_by_filter_by_sport passes" "$SPORT_RESULT" "PASSED"
assert_eq "test_list_by_filter_by_status passes" "$STATUS_RESULT" "PASSED"

# Test 3: full unit suite still green
FULL_OUTPUT=$(
  PYTHONPATH="$REPO_ROOT/api" \
    "$VENV_DIR/bin/pytest" tests/unit/ --tb=short -q 2>&1
)
FULL_EXIT=$?
FULL_RESULT=$( [ "$FULL_EXIT" -eq 0 ] && echo "PASSED" || echo "FAILED" )
assert_eq "full make test-unit suite passes" "$FULL_RESULT" "PASSED"

if [ "$FULL_EXIT" -ne 0 ]; then
  echo ""
  echo "--- pytest output ---"
  echo "$FULL_OUTPUT" | tail -30
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #306: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
