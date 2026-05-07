#!/usr/bin/env bash
# Smoke test for PR #292 — DBL-10 doubles lifecycle integration tests
#
# This PR is tests-only (no production endpoints added).
# The smoke test verifies that all new integration tests pass against the
# Firestore emulator, which is the full acceptance criterion for this PR.
#
# Prerequisites:
#   - Firestore emulator running on 127.0.0.1:8082
#   - main checkout venv at <main-repo>/.venv (resolved automatically)
#
# Usage:
#   bash tests/smoke/pr-292.sh
#
# Optional overrides:
#   FIRESTORE_EMULATOR_HOST=127.0.0.1:8082 \
#   GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0 \
#   bash tests/smoke/pr-292.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Venv resolution ─────────────────────────────────────────────────────────
# Detached PR worktrees do not have their own virtualenv. Fall back to the
# main checkout venv via `git worktree list` so the script works in both
# the main checkout and a detached worktree without requiring VENV to be set.
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR (or $REPO_ROOT/.venv). Run 'make venv && make install' in the main checkout."
  exit 1
fi

FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================================"
echo " PR #292 — DBL-10 doubles lifecycle smoke test"
echo "============================================================"
echo "Emulator host : $FIRESTORE_EMULATOR_HOST"
echo "Project       : $GOOGLE_CLOUD_PROJECT"
echo "PYTHONPATH    : $PYTHONPATH"
echo "Venv          : $VENV_DIR"
echo ""

# ─── 0. Verify emulator is reachable ────────────────────────────────────────
echo "[0/2] Checking Firestore emulator..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://$FIRESTORE_EMULATOR_HOST" || true)
if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "ERROR: Firestore emulator not reachable at http://$FIRESTORE_EMULATOR_HOST"
  echo "  Run: make emu-firestore  (in a separate terminal)"
  exit 1
fi
echo "  OK — emulator responding."
echo ""

# ─── 1. Clear emulator state for a clean run ────────────────────────────────
echo "[1/2] Clearing emulator state..."
curl -s -X DELETE \
  "http://$FIRESTORE_EMULATOR_HOST/emulator/v1/projects/$GOOGLE_CLOUD_PROJECT/databases/(default)/documents" \
  -o /dev/null
echo "  OK — emulator data cleared."
echo ""

# ─── 2. Run the doubles lifecycle integration tests ─────────────────────────
echo "[2/2] Running doubles lifecycle integration tests..."
FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV_DIR/bin/pytest" \
  "$REPO_ROOT/tests/integration/test_doubles_lifecycle_integration.py" \
  -v \
  --tb=short \
  2>&1

echo ""
echo "============================================================"
echo " SMOKE TEST PASSED — PR #292 DBL-10 doubles lifecycle"
echo "============================================================"
