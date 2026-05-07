#!/usr/bin/env bash
# Smoke test for PR #292 — DBL-10 doubles lifecycle integration tests
#
# This PR is tests-only (no production endpoints added).
# The smoke test verifies that all new integration tests pass against the
# Firestore emulator, which is the full acceptance criterion for this PR.
#
# Prerequisites:
#   - Firestore emulator running on 127.0.0.1:8082
#   - PYTHONPATH set to the worktree api/ directory
#   - FIRESTORE_EMULATOR_HOST and GOOGLE_CLOUD_PROJECT set
#
# Usage:
#   FIRESTORE_EMULATOR_HOST=127.0.0.1:8082 \
#   GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0 \
#   PYTHONPATH=/path/to/worktree/api \
#   bash tests/smoke/pr-292.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV="${VENV:-$REPO_ROOT/.venv}"

FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
PYTHONPATH="${PYTHONPATH:-$REPO_ROOT/api}"

echo "============================================================"
echo " PR #292 — DBL-10 doubles lifecycle smoke test"
echo "============================================================"
echo "Emulator host : $FIRESTORE_EMULATOR_HOST"
echo "Project       : $GOOGLE_CLOUD_PROJECT"
echo "PYTHONPATH    : $PYTHONPATH"
echo "Venv          : $VENV"
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
PYTHONPATH="$PYTHONPATH" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/pytest" \
  "$REPO_ROOT/tests/integration/test_doubles_lifecycle_integration.py" \
  -v \
  --tb=short \
  2>&1

echo ""
echo "============================================================"
echo " SMOKE TEST PASSED — PR #292 DBL-10 doubles lifecycle"
echo "============================================================"
