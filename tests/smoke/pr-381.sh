#!/usr/bin/env bash
# Smoke tests for PR #381 - doubles join with an unregistered partner (#367)
#
# Exercises the invite -> claim flow against the Firestore emulator through the
# FastAPI app: partner_invite forms an ACTIVE team immediately (partner_uid null,
# +2 capacity, placeholder member + partnerInvites lookup, email never in the
# response), duplicate/self/registered-email guards, XOR 422, and the
# registration backfill that rewrites the team to the real uid and consumes the
# invite (email deleted, placeholder gone, lookup gone), idempotent on re-run.
#
# Prereqs:
#   - Firestore emulator running on the configured port.
#
# Usage:
#   bash tests/smoke/pr-381.sh

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

echo "PR #381 doubles unregistered-partner invite smoke"

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

run_check "invite -> claim end-to-end via API" env \
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
from app.utils.contact import partner_placeholder_uid

db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])

LEAGUE_ID = "smoke-pr381-doubles"
CAPTAIN = "smoke-pr381-captain"
CLAIMANT = "smoke-pr381-claimant"
INVITE_EMAIL = "Smoke.Nick@Example.com"
INVITE_EMAIL_NORM = "smoke.nick@example.com"
PLACEHOLDER = partner_placeholder_uid(INVITE_EMAIL_NORM)


def cleanup() -> None:
    league_ref = db.collection("leagues").document(LEAGUE_ID)
    for sub in ("members", "teams", "divisions"):
        for d in league_ref.collection(sub).stream():
            d.reference.delete()
    league_ref.delete()
    for d in db.collection("partnerInvites").where("emailNormalized", "==", INVITE_EMAIL_NORM).stream():
        d.reference.delete()
    for uid in (CAPTAIN, CLAIMANT):
        db.collection("users").document(uid).delete()


def seed() -> None:
    db.collection("leagues").document(LEAGUE_ID).set(
        {
            "name": "Smoke Doubles",
            "sport": "padel",
            "status": "open",
            "ownerUid": CAPTAIN,
            "format": "doubles",
            "maxPlayers": 8,
            "currentPlayers": 0,
            "startDate": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "divisionConfig": {"targetSize": 6, "maxDivisions": None},
        }
    )
    db.collection("users").document(CAPTAIN).set(
        {
            "uid": CAPTAIN,
            "name": "Smoke Captain",
            "email": "smoke.captain@example.com",
            "rankings": {"padel": {"pts": 1500}},
        }
    )


cleanup()
seed()
app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
app.dependency_overrides[get_league_service] = lambda: LeagueService(LeaguesRepo(db), db)
app.dependency_overrides[get_current_user] = lambda: CurrentUser(
    uid=CAPTAIN, email="smoke.captain@example.com", display_name="Smoke Captain"
)
client = TestClient(app)

try:
    # 1. Invite unregistered partner -> 201 ACTIVE, no email, +2 capacity
    r = client.post(
        f"/leagues/{LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Nick", "email": INVITE_EMAIL, "phone": "+30123"}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active", body
    assert body["partner_uid"] is None, body
    assert body["partner_placeholder_uid"] == PLACEHOLDER, body
    assert body["partner_invite"] == {"name": "Nick", "phone": "+30123"}, body
    assert "email" not in body["partner_invite"], body
    team_id = body["team_id"]

    league = db.collection("leagues").document(LEAGUE_ID).get().to_dict()
    assert league["currentPlayers"] == 2, league

    lookup_id = f"{PLACEHOLDER}__{LEAGUE_ID}"
    lookup = db.collection("partnerInvites").document(lookup_id).get().to_dict()
    assert lookup["emailNormalized"] == INVITE_EMAIL_NORM, lookup

    # 2. Duplicate email same league -> 409
    r = client.post(
        f"/leagues/{LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Nick", "email": INVITE_EMAIL}},
    )
    assert r.status_code == 409, r.text

    # 3. Self email -> 400
    r = client.post(
        f"/leagues/{LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Me", "email": "smoke.captain@example.com"}},
    )
    assert r.status_code == 400, r.text

    # 4. Both fields -> 422
    r = client.post(
        f"/leagues/{LEAGUE_ID}/join",
        json={"partner_uid": "x", "partner_invite": {"name": "Nick", "email": "n@example.com"}},
    )
    assert r.status_code == 422, r.text

    # 5. Invited person registers with that email -> claim backfills
    db.collection("users").document(CLAIMANT).set(
        {"uid": CLAIMANT, "name": "Real Nick", "email": INVITE_EMAIL_NORM, "emailLower": INVITE_EMAIL_NORM}
    )
    LeagueService(LeaguesRepo(db), db).claim_partner_invites(CLAIMANT, INVITE_EMAIL)

    team = db.collection("leagues").document(LEAGUE_ID).collection("teams").document(team_id).get().to_dict()
    assert team["partnerUid"] == CLAIMANT, team
    assert team["memberUids"] == [CAPTAIN, CLAIMANT], team
    assert "partnerInvite" not in team, team
    assert "partnerPlaceholderUid" not in team, team

    members = {
        d.id: d.to_dict()
        for d in db.collection("leagues").document(LEAGUE_ID).collection("members").stream()
    }
    assert PLACEHOLDER not in members, members
    assert CLAIMANT in members, members
    assert members[CAPTAIN]["partnerUid"] == CLAIMANT, members

    assert not db.collection("partnerInvites").document(lookup_id).get().exists

    # 6. Idempotent re-run
    LeagueService(LeaguesRepo(db), db).claim_partner_invites(CLAIMANT, INVITE_EMAIL)
    team2 = db.collection("leagues").document(LEAGUE_ID).collection("teams").document(team_id).get().to_dict()
    assert team2["partnerUid"] == CLAIMANT, team2

    print("invite -> claim flow OK")
finally:
    cleanup()
    app.dependency_overrides = {}
PY

run_check "partner-invite unit + integration suites pass" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/pytest" \
  tests/unit/repos/test_partner_invite_mapper.py \
  tests/unit/routers/test_league_partner_invite_router.py \
  tests/unit/services/test_onboarding_claim_hook.py \
  tests/integration/test_partner_invite_integration.py \
  -q

run_check "endpoints doc covers partner_invite" grep -q "partner_invite" docs/api/endpoints.md
run_check "contracts doc covers partner_invite" grep -q "partner_invite" docs/api/contracts.md
run_check "data dictionary covers partnerInvites collection" \
  grep -q "partnerInvites" docs/data/data-dictionary.md

echo ""
echo "Smoke tests PR #381: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #381."
