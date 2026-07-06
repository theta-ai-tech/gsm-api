#!/usr/bin/env bash
# Smoke tests for PR #368 - Leagues doubles/team join contract (#366)
#
# Exercises the full doubles flow against the Firestore emulator through the
# FastAPI app: player prefix search, doubles invite (pending team + intent),
# accept (members + capacity), decline guard, kickoff (team seeding), and
# team-shaped standings. Singles join is regression-checked.
#
# Prereqs:
#   - Firestore emulator running on the configured port.
#
# Usage:
#   bash tests/smoke/pr-368.sh

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_REPO_ROOT="$(git -C "$REPO_ROOT" worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
VENV="${VENV:-$MAIN_REPO_ROOT/.venv}"
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

echo "PR #368 doubles/team join smoke"

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

run_check "doubles end-to-end flow via API" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" - <<'PY'
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.dependencies.repos import get_league_service, get_leagues_repo, get_users_repo
from app.deps import get_current_user, get_role_service
from app.main import app
from app.repos.leagues_repo import LeaguesRepo
from app.repos.notification_intent_repo import NotificationIntentRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService
from app.services.role_service import RoleService

LEAGUE_ID = "pr-368-doubles-smoke"
USERS = [
    ("pr368-cap1", "Pr368 Capone", 1400),
    ("pr368-par1", "Pr368 Parone", 1200),
    ("pr368-cap2", "Pr368 Captwo", 800),
    ("pr368-par2", "Pr368 Partwo", 600),
]
db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
league_ref = db.collection("leagues").document(LEAGUE_ID)


def cleanup() -> None:
    for sub in ("members", "teams", "divisions"):
        for doc in league_ref.collection(sub).stream():
            doc.reference.delete()
    league_ref.delete()
    for uid, _n, _p in USERS:
        uref = db.collection("users").document(uid)
        for doc in uref.collection("notificationIntents").stream():
            doc.reference.delete()
        uref.delete()


cleanup()
league_ref.set(
    {
        "name": "PR 368 Doubles Smoke",
        "sport": "padel",
        "status": "open",
        "format": "doubles",
        "ownerUid": USERS[0][0],
        "maxPlayers": 8,
        "currentPlayers": 0,
        "startDate": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }
)
for uid, name, pts in USERS:
    db.collection("users").document(uid).set(
        {"uid": uid, "name": name, "nameLower": name.lower(), "rankings": {"padel": {"pts": pts}}}
    )


class Auth:
    uid = USERS[0][0]

    def __call__(self):
        return CurrentUser(uid=self.uid, email=f"{self.uid}@gsm.local")


auth = Auth()
app.dependency_overrides[get_current_user] = auth
app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
app.dependency_overrides[get_league_service] = lambda: LeagueService(
    LeaguesRepo(db), db, notification_intent_repo=NotificationIntentRepo(db)
)
app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
client = TestClient(app)

try:
    # 1. player prefix search excludes caller, includes partners
    r = client.get("/players?search=pr368&sport=padel")
    assert r.status_code == 200, r.text
    uids = [p["uid"] for p in r.json()["players"]]
    assert "pr368-cap1" not in uids and "pr368-par1" in uids, uids

    # 2. doubles invite -> pending team, no capacity, partner intent written
    r = client.post(f"/leagues/{LEAGUE_ID}/join", json={"partner_uid": "pr368-par1"})
    assert r.status_code == 201, r.text
    team1 = r.json()
    assert team1["status"] == "pending"
    assert league_ref.get().to_dict()["currentPlayers"] == 0
    intents = [
        d.to_dict()["type"]
        for d in db.collection("users").document("pr368-par1")
        .collection("notificationIntents").stream()
    ]
    assert "league_team_invite" in intents, intents

    # 3. missing partner on doubles league -> 400
    assert client.post(f"/leagues/{LEAGUE_ID}/join").status_code == 400

    # 4. wrong actor accept -> 403; partner accept -> members + capacity +2
    auth.uid = "pr368-cap2"
    assert client.post(f"/leagues/{LEAGUE_ID}/teams/{team1['team_id']}/accept").status_code == 403
    auth.uid = "pr368-par1"
    r = client.post(f"/leagues/{LEAGUE_ID}/teams/{team1['team_id']}/accept")
    assert r.status_code == 200, r.text
    assert league_ref.get().to_dict()["currentPlayers"] == 2
    member = league_ref.collection("members").document("pr368-cap1").get().to_dict()
    assert member["uid"] == "pr368-cap1" and member["teamId"] == team1["team_id"], member

    # 5. second team + accept; declined invite cannot be re-accepted
    auth.uid = "pr368-cap2"
    team2 = client.post(
        f"/leagues/{LEAGUE_ID}/join", json={"partner_uid": "pr368-par2"}
    ).json()
    auth.uid = "pr368-par2"
    assert client.post(f"/leagues/{LEAGUE_ID}/teams/{team2['team_id']}/accept").status_code == 200
    assert league_ref.get().to_dict()["currentPlayers"] == 4

    # 6. mine=true surfaces the caller's team
    r = client.get(f"/leagues/{LEAGUE_ID}/teams?mine=true")
    assert r.status_code == 200 and len(r.json()["teams"]) == 1, r.text

    # 7. kickoff as owner: 2 teams -> 1 division, teammates together, 4 players
    auth.uid = "pr368-cap1"
    r = client.post(f"/leagues/{LEAGUE_ID}/kickoff")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["division_count"] == 1 and body["divisions"][0]["current_players"] == 4, body
    assert body["divisions"][0]["rating_range"] == {"min": 700, "max": 1300}, body
    t1 = league_ref.collection("teams").document(team1["team_id"]).get().to_dict()
    assert t1["divisionId"] == "div-1", t1

    # 8. standings rows are teams
    r = client.get(f"/leagues/{LEAGUE_ID}/standings")
    assert r.status_code == 200, r.text
    rows = r.json()["standings"]
    assert len(rows) == 2 and all(row["team_id"] for row in rows), rows
    assert all(" / " in row["display_name"] for row in rows), rows

    print("doubles flow OK")
finally:
    cleanup()
    app.dependency_overrides = {}
PY

run_check "singles join regression (format absent => singles)" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" - <<'PY'
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.dependencies.repos import get_league_service, get_leagues_repo
from app.deps import get_current_user
from app.main import app
from app.repos.leagues_repo import LeaguesRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService

LEAGUE_ID = "pr-368-singles-smoke"
UID = "pr368-singles-user"
db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
league_ref = db.collection("leagues").document(LEAGUE_ID)


def cleanup() -> None:
    for doc in league_ref.collection("members").stream():
        doc.reference.delete()
    league_ref.delete()


cleanup()
# No `format` field at all — must behave as singles.
league_ref.set(
    {
        "name": "PR 368 Singles Smoke",
        "sport": "tennis",
        "status": "open",
        "ownerUid": "someone",
        "maxPlayers": 4,
        "currentPlayers": 0,
        "startDate": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }
)
app.dependency_overrides[get_current_user] = lambda: CurrentUser(
    uid=UID, email=f"{UID}@gsm.local"
)
app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
app.dependency_overrides[get_league_service] = lambda: LeagueService(LeaguesRepo(db), db)
client = TestClient(app)

try:
    # bodyless join still works and returns a LeagueMember
    r = client.post(f"/leagues/{LEAGUE_ID}/join")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["uid"] == UID and body["team_id"] is None, body
    assert league_ref.get().to_dict()["currentPlayers"] == 1
    # partner_uid on a singles league -> 400
    r = client.post(f"/leagues/{LEAGUE_ID}/join", json={"partner_uid": "whoever"})
    assert r.status_code == 400, r.text
    print("singles regression OK")
finally:
    cleanup()
    app.dependency_overrides = {}
PY

run_check "doubles unit suites pass" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$VENV/bin/pytest" \
  tests/unit/services/test_league_team_join.py \
  tests/unit/services/test_league_team_kickoff_standings.py \
  tests/unit/routers/test_league_teams.py \
  tests/unit/routers/test_players.py \
  -q

run_check "contract docs cover doubles join" grep -q "partner_uid" docs/api/contracts.md
run_check "endpoint docs cover accept" grep -q "teams/{team_id}/accept" docs/api/endpoints.md
run_check "data dictionary has teams subcollection" grep -q "leagues/{leagueId}/teams" docs/data/data-dictionary.md
run_check "data dictionary documents nameLower" grep -q "nameLower" docs/data/data-dictionary.md

echo ""
echo "Smoke tests PR #368: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #368."
