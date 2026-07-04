#!/usr/bin/env bash
# Smoke tests for PR #362 - LDIV-3 division read endpoints (#358)
#
# Prereqs:
#   - API started from THIS worktree.
#   - Firestore/Auth emulators running on the configured ports.
#
# Usage:
#   API_BASE_URL=http://127.0.0.1:8362 bash tests/smoke/pr-362.sh

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_REPO_ROOT="$(git -C "$REPO_ROOT" worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
VENV="${VENV:-$MAIN_REPO_ROOT/.venv}"
API="${API_BASE_URL:-http://127.0.0.1:8362}"
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
LEAGUE_ID="pr-362-division-read"
PENDING_LEAGUE_ID="pr-362-division-pending"
USER_UID="user_pr_362_reader"

ok() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
no() { echo "  FAIL: $1"; echo "    $2"; FAIL=$((FAIL + 1)); }

assert_eq() {
  local name="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    ok "$name"
  else
    no "$name" "expected '$expected', got '$actual'"
  fi
}

run_check() {
  local name="$1"
  shift
  if "$@"; then
    ok "$name"
  else
    no "$name" "command failed: $*"
  fi
}

echo "PR #362 LDIV-3 smoke - API=$API"

if [ -x "$VENV/bin/python" ] && [ -x "$VENV/bin/pytest" ]; then
  ok "main repo venv available"
else
  no "main repo venv available" "missing $VENV/bin/python or $VENV/bin/pytest"
fi

if curl -fsS "$API/health" >/dev/null 2>&1; then
  ok "API reachable at \$API_BASE_URL/health"
else
  no "API reachable at \$API_BASE_URL/health" "set API_BASE_URL to the PR worktree API"
fi

run_check "Firestore emulator reachable" env \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" -c "from google.cloud import firestore; list(firestore.Client(project='$GOOGLE_CLOUD_PROJECT').collections())"

run_check "Auth emulator reachable" curl -fsS -o /dev/null \
  "http://$FIREBASE_AUTH_EMULATOR_HOST/emulator/v1/projects/$GOOGLE_CLOUD_PROJECT/config"

run_check "worktree app import wins" env \
  PYTHONPATH="$REPO_ROOT/api" \
  "$VENV/bin/python" -c "import app, os; assert os.path.dirname(app.__file__).startswith('$REPO_ROOT/api/app')"

run_check "seed division read fixture" env \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" - "$LEAGUE_ID" "$PENDING_LEAGUE_ID" "$USER_UID" <<'PY'
from datetime import datetime, timezone
import os
import sys
from google.cloud import firestore

league_id, pending_league_id, uid = sys.argv[1:4]
db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-f70d0"))
match_ids = [
    "pr-362-upcoming-div1",
    "pr-362-upcoming-div2",
    "pr-362-completed-div1",
    "pr-362-completed-div2",
]

def cleanup() -> None:
    for match_id in match_ids:
        db.collection("matches").document(match_id).delete()
    for lid in (league_id, pending_league_id):
        league_ref = db.collection("leagues").document(lid)
        for doc in league_ref.collection("members").stream():
            doc.reference.delete()
        for doc in league_ref.collection("divisions").stream():
            doc.reference.delete()
        league_ref.delete()
    db.collection("users").document(uid).delete()

def member(wins: int, losses: int, division_id: str | None) -> dict:
    return {
        "role": "player",
        "status": "active",
        "joinedAt": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "stats": {"wins": wins, "losses": losses},
        "divisionId": division_id,
    }

def match_doc(match_id: str, status: str, division_id: str) -> dict:
    scheduled_at = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc)
    return {
        "sport": "padel",
        "status": status,
        "matchType": "singles",
        "scheduledAt": scheduled_at if status == "scheduled" else None,
        "finishedAt": finished_at if status == "completed" else None,
        "leagueId": league_id,
        "divisionId": division_id,
        "participantUids": [f"{match_id}_a", f"{match_id}_b"],
        "participants": [
            {"uid": f"{match_id}_a", "role": "player"},
            {"uid": f"{match_id}_b", "role": "player"},
        ],
    }

cleanup()
db.collection("users").document(uid).set({"name": "PR 362 Reader"})

league_ref = db.collection("leagues").document(league_id)
league_ref.set(
    {
        "name": "PR 362 Division League",
        "sport": "padel",
        "status": "active",
        "ownerUid": "owner",
        "dividedAt": datetime(2026, 8, 2, tzinfo=timezone.utc),
    }
)
league_ref.collection("divisions").document("div-2").set(
    {
        "name": "Division 2",
        "ordinal": 2,
        "ratingRange": {"min": 700, "max": 899},
        "currentPlayers": 1,
        "status": "active",
    }
)
league_ref.collection("divisions").document("div-1").set(
    {
        "name": "Division 1",
        "ordinal": 1,
        "ratingRange": {"min": 900, "max": 1400},
        "currentPlayers": 2,
        "status": "active",
    }
)
league_ref.collection("members").document(uid).set(member(4, 0, "div-1"))
league_ref.collection("members").document("pr-362-low").set(member(1, 2, "div-1"))
league_ref.collection("members").document("pr-362-other").set(member(9, 0, "div-2"))

pending_ref = db.collection("leagues").document(pending_league_id)
pending_ref.set(
    {
        "name": "PR 362 Pending Division League",
        "sport": "padel",
        "status": "open",
        "ownerUid": "owner",
    }
)
pending_ref.collection("members").document(uid).set(member(0, 0, None))

db.collection("matches").document("pr-362-upcoming-div1").set(
    match_doc("pr-362-upcoming-div1", "scheduled", "div-1")
)
db.collection("matches").document("pr-362-upcoming-div2").set(
    match_doc("pr-362-upcoming-div2", "scheduled", "div-2")
)
db.collection("matches").document("pr-362-completed-div1").set(
    match_doc("pr-362-completed-div1", "completed", "div-1")
)
db.collection("matches").document("pr-362-completed-div2").set(
    match_doc("pr-362-completed-div2", "completed", "div-2")
)
PY

TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" "$USER_UID" -t 2>/dev/null)
if [ -n "$TOKEN" ]; then
  ok "auth token acquired"
else
  no "auth token acquired" "scripts/get_emu_token.sh returned empty token for $USER_UID"
fi

UNAUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/leagues/$LEAGUE_ID/divisions")
assert_eq "division list requires auth" "$UNAUTH_STATUS" "401"

DIVISIONS_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues/$LEAGUE_ID/divisions")
DIVISION_IDS=$(echo "$DIVISIONS_JSON" | "$VENV/bin/python" -c "import json,sys; data=json.load(sys.stdin); print(','.join(d['division_id'] for d in data['divisions']))")
assert_eq "divisions ordered by ordinal" "$DIVISION_IDS" "div-1,div-2"

STANDINGS_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues/$LEAGUE_ID/divisions/div-1/standings")
STANDING_UIDS=$(echo "$STANDINGS_JSON" | "$VENV/bin/python" -c "import json,sys; data=json.load(sys.stdin); print(','.join(row['uid'] for row in data['standings']))")
assert_eq "division standings filter flat members" "$STANDING_UIDS" "$USER_UID,pr-362-low"

UPCOMING_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues/$LEAGUE_ID/divisions/div-1/matches")
UPCOMING_IDS=$(echo "$UPCOMING_JSON" | "$VENV/bin/python" -c "import json,sys; data=json.load(sys.stdin); print(','.join(row['match_id'] for row in data['matches']))")
assert_eq "division upcoming matches filter by divisionId" "$UPCOMING_IDS" "pr-362-upcoming-div1"

COMPLETED_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues/$LEAGUE_ID/divisions/div-1/matches?type=completed")
COMPLETED_IDS=$(echo "$COMPLETED_JSON" | "$VENV/bin/python" -c "import json,sys; data=json.load(sys.stdin); print(','.join(row['match_id'] for row in data['matches']))")
assert_eq "division completed matches filter by divisionId" "$COMPLETED_IDS" "pr-362-completed-div1"

UNKNOWN_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/leagues/$LEAGUE_ID/divisions/nope/standings")
assert_eq "unknown division returns 404" "$UNKNOWN_STATUS" "404"

PENDING_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues/$PENDING_LEAGUE_ID/divisions")
PENDING_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/leagues/$PENDING_LEAGUE_ID/divisions")
PENDING_DETAIL=$(echo "$PENDING_JSON" | "$VENV/bin/python" -c "import json,sys; print(json.load(sys.stdin)['detail'])")
assert_eq "pre-kickoff division list returns 409" "$PENDING_STATUS" "409"
assert_eq "pre-kickoff detail is stable" "$PENDING_DETAIL" "league not yet divided"

run_check "focused tests pass" env \
  PYTHONPATH="$REPO_ROOT/api" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  FIREBASE_AUTH_EMULATOR_HOST="$FIREBASE_AUTH_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/pytest" \
  tests/unit/repos/test_mappers.py \
  tests/unit/repos/test_matches_repo.py \
  tests/unit/services/test_league_service.py \
  tests/unit/routers/test_leagues_router.py \
  tests/integration/test_league_divisions_read_integration.py \
  -q

run_check "OpenAPI exposes division endpoints" "$VENV/bin/python" - "$API" <<'PY'
import json
import sys
import urllib.request

api = sys.argv[1]
with urllib.request.urlopen(f"{api}/openapi.json", timeout=5) as response:
    spec = json.load(response)
for path in (
    "/leagues/{league_id}/divisions",
    "/leagues/{league_id}/divisions/{division_id}/standings",
    "/leagues/{league_id}/divisions/{division_id}/matches",
):
    assert path in spec["paths"], path
    assert "get" in spec["paths"][path], path
PY

run_check "endpoint docs mention division matches" grep -q "GET /leagues/{league_id}/divisions/{division_id}/matches" docs/api/endpoints.md
run_check "contracts mention division standings" grep -q "GET /leagues/{id}/divisions/{divisionId}/standings" docs/api/contracts.md
run_check "data docs mention divisionId index" grep -q "divisionId.*status.*scheduledAt" docs/data/data-dictionary.md

echo ""
echo "Smoke tests PR #362: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #362."
