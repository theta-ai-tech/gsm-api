#!/usr/bin/env bash
# Smoke tests for PR #360 - LDIV-1: League Divisions schema foundations (#356)
#
# Prereqs:
#   - API started from THIS worktree.
#   - Firestore emulator available via FIRESTORE_EMULATOR_HOST (default 127.0.0.1:8082).
#
# Usage:
#   API_BASE_URL=http://127.0.0.1:8360 bash tests/smoke/pr-360.sh

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_REPO_ROOT="$(git -C "$REPO_ROOT" worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
VENV="${VENV:-$MAIN_REPO_ROOT/.venv}"
API="${API_BASE_URL:-http://127.0.0.1:8360}"
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"

ok() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
no() { echo "  FAIL: $1"; echo "    $2"; FAIL=$((FAIL + 1)); }

run_check() {
  local name="$1"
  shift
  if "$@"; then
    ok "$name"
  else
    no "$name" "command failed: $*"
  fi
}

echo "PR #360 LDIV-1 smoke - API=$API"

if curl -fsS "$API/health" >/dev/null 2>&1; then
  ok "API reachable at \$API_BASE_URL/health"
else
  no "API reachable at \$API_BASE_URL/health" "set API_BASE_URL to the PR worktree API"
fi

if [ -x "$VENV/bin/python" ] && [ -x "$VENV/bin/pytest" ]; then
  ok "main repo venv available"
else
  no "main repo venv available" "missing $VENV/bin/python or $VENV/bin/pytest"
fi

run_check "Firestore emulator reachable" env \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" -c "from google.cloud import firestore; list(firestore.Client(project='$GOOGLE_CLOUD_PROJECT').collections())"

run_check "worktree app import wins" env \
  PYTHONPATH="$REPO_ROOT/api" \
  "$VENV/bin/python" -c "import app, os; assert os.path.dirname(app.__file__).startswith('$REPO_ROOT/api/app')"

run_check "focused unit tests pass" env \
  PYTHONPATH="$REPO_ROOT/api" \
  "$VENV/bin/pytest" \
  tests/unit/repos/test_mappers.py \
  tests/unit/repos/test_divisions_repo.py \
  -q

run_check "division repo integration test passes" env \
  PYTHONPATH="$REPO_ROOT/api" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/pytest" \
  tests/integration/test_divisions_repo_integration.py \
  -q

run_check "data dictionary documents LDIV schema" grep -q "divisionConfig" docs/data/data-dictionary.md
run_check "data dictionary documents divisions subcollection" grep -q "leagues/{leagueId}/divisions" docs/data/data-dictionary.md
run_check "data dictionary documents member divisionId" grep -q "divisionId" docs/data/data-dictionary.md

echo ""
echo "Smoke tests PR #360: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #360."
