#!/usr/bin/env bash
# Smoke tests for PR #361 - LDIV-2 kickoff endpoint + division split (#357)
#
# Prereqs:
#   - API started from THIS worktree.
#   - Firestore/Auth emulators running on the configured ports.
#
# Usage:
#   API_BASE_URL=http://127.0.0.1:8361 bash tests/smoke/pr-361.sh

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_REPO_ROOT="$(git -C "$REPO_ROOT" worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
VENV="${VENV:-$MAIN_REPO_ROOT/.venv}"
API="${API_BASE_URL:-http://127.0.0.1:8361}"
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
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

echo "PR #361 LDIV-2 smoke - API=$API"

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

run_check "Auth emulator reachable" curl -fsS \
  "http://$FIREBASE_AUTH_EMULATOR_HOST/emulator/v1/projects/$GOOGLE_CLOUD_PROJECT/config"

run_check "worktree app import wins" env \
  PYTHONPATH="$REPO_ROOT/api" \
  "$VENV/bin/python" -c "import app, os; assert os.path.dirname(app.__file__).startswith('$REPO_ROOT/api/app')"

run_check "focused unit tests pass" env \
  PYTHONPATH="$REPO_ROOT/api" \
  "$VENV/bin/pytest" \
  tests/unit/services/test_league_service.py \
  tests/unit/routers/test_leagues_router.py \
  tests/unit/repos/test_mappers.py \
  -q

run_check "kickoff integration test passes" env \
  PYTHONPATH="$REPO_ROOT/api" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  FIREBASE_AUTH_EMULATOR_HOST="$FIREBASE_AUTH_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/pytest" \
  tests/integration/test_league_kickoff_integration.py \
  -q

run_check "OpenAPI exposes kickoff endpoint" "$VENV/bin/python" - "$API" <<'PY'
import json
import sys
import urllib.request

api = sys.argv[1]
with urllib.request.urlopen(f"{api}/openapi.json", timeout=5) as response:
    spec = json.load(response)
assert "/leagues/{league_id}/kickoff" in spec["paths"]
assert "post" in spec["paths"]["/leagues/{league_id}/kickoff"]
PY

run_check "endpoint docs mention kickoff" grep -q "POST /leagues/{league_id}/kickoff" docs/api/endpoints.md
run_check "contracts mention kickoff" grep -q "POST /leagues/{id}/kickoff" docs/api/contracts.md
run_check "trigger docs mention kickoff claim" grep -q "open.*dividing" docs/architecture/triggers.md

echo ""
echo "Smoke tests PR #361: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #361."
