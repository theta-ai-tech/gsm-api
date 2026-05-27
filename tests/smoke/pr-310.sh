#!/usr/bin/env bash
# Smoke tests for PR #310: test: LG-15 integration tests — league browse, join, standings, matches (#262)
# Generated: 2026-05-27
# Usage: bash tests/smoke/pr-310.sh
#
# Requires: Firestore emulator running (make emu-all).
# No API process needed — tests use FastAPI TestClient directly.

set -uo pipefail

PASS=0
FAIL=0

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="${MAIN_WT}/.venv"
fi

if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
  exit 1
fi

# ── Emulator preflight ────────────────────────────────────────────────────
FIRESTORE_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"

echo "Preflighting Firestore emulator at $FIRESTORE_HOST ..."
if ! curl -fsS "http://${FIRESTORE_HOST}/v1/projects/${PROJECT}/databases/(default)/documents/" >/dev/null 2>&1; then
  echo "ERROR: Firestore emulator not reachable at $FIRESTORE_HOST. Run 'make emu-all' first."
  exit 1
fi
echo "  ✓ Firestore emulator reachable"

# ── Run integration tests ────────────────────────────────────────────────
echo ""
echo "Running LG-15 integration tests (PR #310) ..."
echo ""

TEST_OUTPUT=$(
  PYTHONPATH="$REPO_ROOT/api" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_HOST" \
  FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}" \
  GOOGLE_CLOUD_PROJECT="$PROJECT" \
  FIREBASE_PROJECT_ID="$PROJECT" \
  CORS_ORIGIN="http://localhost:3000" \
  "$VENV_DIR/bin/pytest" \
    "$REPO_ROOT/tests/integration/test_leagues_integration.py" \
    -v --tb=short -p no:warnings 2>&1
)

echo "$TEST_OUTPUT"

# ── Parse pytest results ──────────────────────────────────────────────────
PASSED=$(echo "$TEST_OUTPUT" | grep -E "^\.claude.*PASSED" | wc -l | tr -d ' ')
FAILED=$(echo "$TEST_OUTPUT" | grep -E "^\.claude.*FAILED" | wc -l | tr -d ' ')
ERROR=$(echo "$TEST_OUTPUT" | grep -E "^\.claude.*ERROR" | wc -l | tr -d ' ')

PASS=$PASSED
FAIL=$((FAILED + ERROR))

# ── Summary ──────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #310: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
