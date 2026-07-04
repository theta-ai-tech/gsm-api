#!/usr/bin/env bash
# Smoke tests for PR #365 - LDIV-4 LeagueSummary divisionId cache propagation (#359)
#
# Prereqs:
#   - Firestore emulator running on the configured port.
#
# Usage:
#   bash tests/smoke/pr-365.sh

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_REPO_ROOT="$(git -C "$REPO_ROOT" worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
VENV="${VENV:-$MAIN_REPO_ROOT/.venv}"
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
LEAGUE_ID="pr-365-summary-division"
USER_UID="user_pr_365_summary"

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

echo "PR #365 LDIV-4 smoke"

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
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$VENV/bin/python" -c "import app, os; assert os.path.dirname(app.__file__).startswith('$REPO_ROOT/api/app')"

run_check "divisionId member update refreshes league summary cache" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" - "$LEAGUE_ID" "$USER_UID" <<'PY'
import os
import sys

from google.cloud import firestore

from functions.league_triggers.on_league_member_write import (
    handle_league_member_upsert,
    qualify_league_member_upsert,
)

league_id, uid = sys.argv[1:3]
db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-f70d0"))
league_ref = db.collection("leagues").document(league_id)
user_ref = db.collection("users").document(uid)
member_ref = league_ref.collection("members").document(uid)

member_ref.delete()
league_ref.delete()
user_ref.delete()

user_ref.set({"uid": uid, "name": "PR 365 Summary", "leaguesActive": []})
league_ref.set(
    {
        "name": "PR 365 League",
        "sport": "padel",
        "status": "active",
    }
)

before = {
    "uid": uid,
    "role": "player",
    "status": "active",
    "displayName": "PR 365 Summary",
    "divisionId": None,
}
after = {**before, "divisionId": "div-1"}
member_ref.set(after)

result = qualify_league_member_upsert(league_id, before, after)
assert result.qualifies is True
assert handle_league_member_upsert(db, league_id, before, after) is True

cached = user_ref.get().to_dict()["leaguesActive"]
assert len(cached) == 1
summary = cached[0]
assert summary["leagueId"] == league_id
assert summary["divisionId"] == "div-1"
assert summary["role"] == "player"

# Replaying the same member doc is a no-op, proving qualification still protects retries.
replay = qualify_league_member_upsert(league_id, after, after)
assert replay.qualifies is False
assert replay.reason == "no_op"
PY

run_check "LeagueSummary round-trip and trigger unit tests pass" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$VENV/bin/pytest" \
  tests/unit/repos/test_mappers.py \
  tests/tools/test_seed_mapping.py \
  tests/unit/test_league_summary_division_id.py \
  tests/unit/test_league_summaries_upsert.py \
  tests/unit/test_league_summaries_remove.py \
  -q

run_check "trigger docs mention divisionId summary" grep -q "role, divisionId" docs/architecture/triggers.md
run_check "trigger docs keep scoring route by leagueId" grep -q "match.leagueId" docs/architecture/triggers.md
run_check "trigger docs exclude divisionId from scoring" grep -q "matches.divisionId.*not consulted" docs/architecture/triggers.md
run_check "data dictionary mentions summary divisionId" grep -q "leaguesActive.*divisionId" docs/data/data-dictionary.md

echo ""
echo "Smoke tests PR #365: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #365."
