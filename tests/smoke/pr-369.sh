#!/usr/bin/env bash
# Smoke tests for PR #369 - DELETE /me/account anonymize-in-place (ACCT-1, #363)
#
# Exercises account deletion against the Firestore emulator through the FastAPI
# app with a faked Auth admin (no Auth emulator dependency): 204 response,
# erasure-before-identity ordering, own subcollections + device tokens hard-deleted,
# user doc tombstoned (uid + rankings kept, PII stripped), no cascade onto match or
# opponent docs, opponent rivalry still resolves as "Deleted Player", and an
# already-gone Auth user is idempotent. The auth-dependency 401 mapping for
# deleted/disabled users is regression-checked via the unit suite.
#
# Prereqs:
#   - Firestore emulator running on the configured port.
#
# Usage:
#   bash tests/smoke/pr-369.sh

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

echo "PR #369 DELETE /me/account anonymize-in-place smoke"

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

run_check "account deletion end-to-end via API" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" - <<'PY'
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.cloud import firestore

from app.dependencies.repos import (
    get_auth_admin,
    get_journal_repo,
    get_matches_repo,
    get_point_history_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.main import app
from app.models import compute_participant_pair
from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

TARGET = "pr369-del-target"
OPPONENT = "pr369-del-opponent"
MATCH_ID = "pr369-match"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])


class FakeAuthAdmin:
    """Records the single destructive Auth op; no separate revoke exists."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_user(self, uid: str) -> None:
        self.deleted.append(uid)


def cleanup() -> None:
    for uid in (TARGET, OPPONENT):
        ref = db.collection("users").document(uid)
        for sub in ("journalEntries", "pointHistory"):
            for doc in ref.collection(sub).stream():
                doc.reference.delete()
        ref.delete()
    db.collection("matches").document(MATCH_ID).delete()


def seed() -> None:
    users = db.collection("users")
    users.document(TARGET).set(
        {
            "uid": TARGET,
            "name": "Target Player",
            "email": "target@example.com",
            "phone": "+301234567890",
            "profileUrl": "http://example.com/t.png",
            "preferences": {"area": 101, "sports": ["padel"]},
            "deviceTokens": [
                {"token": "tok_target", "platform": "ios", "createdAt": NOW, "lastSeenAt": NOW}
            ],
            "rankings": {"padel": {"sport": "padel", "pts": 1200, "tier": "amateur"}},
        }
    )
    users.document(TARGET).collection("journalEntries").document("j1").set(
        {"uid": TARGET, "createdAt": NOW, "title": "note", "body": "b", "visibility": "private"}
    )
    users.document(TARGET).collection("pointHistory").document("p1").set(
        {"sport": "padel", "pts": 1200, "delta": 20, "reason": "match_win", "createdAt": NOW}
    )
    users.document(OPPONENT).set(
        {
            "uid": OPPONENT,
            "name": "Opponent Player",
            "email": "opp@example.com",
            "preferences": {"area": 101, "sports": ["padel"]},
            "rankings": {"padel": {"sport": "padel", "pts": 1100, "tier": "amateur"}},
        }
    )
    pair = compute_participant_pair([TARGET, OPPONENT])
    db.collection("matches").document(MATCH_ID).set(
        {
            "sport": "padel",
            "status": "completed",
            "matchType": "singles",
            "participantUids": [TARGET, OPPONENT],
            "participantPair": pair,
            "resultByUser": {TARGET: "W", OPPONENT: "L"},
            "finishedAt": NOW,
        }
    )


cleanup()
seed()
fake_auth = FakeAuthAdmin()
app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
app.dependency_overrides[get_journal_repo] = lambda: JournalRepo(db)
app.dependency_overrides[get_point_history_repo] = lambda: PointHistoryRepo(db)
app.dependency_overrides[get_matches_repo] = lambda: MatchesRepo(db)
app.dependency_overrides[get_auth_admin] = lambda: fake_auth
app.dependency_overrides[get_current_user] = lambda: CurrentUser(uid=TARGET, email=None)
client = TestClient(app)

try:
    # 1. delete self -> 204, empty body
    r = client.request("DELETE", "/me/account")
    assert r.status_code == 204, r.text
    assert r.content == b""

    # 2. Auth user deleted exactly once (single destructive Auth op, no revoke)
    assert fake_auth.deleted == [TARGET], fake_auth.deleted
    assert not hasattr(fake_auth, "revoke_refresh_tokens")

    # 3. own subcollections hard-deleted
    tref = db.collection("users").document(TARGET)
    assert list(tref.collection("journalEntries").stream()) == []
    assert list(tref.collection("pointHistory").stream()) == []

    # 4. user doc tombstoned: uid + rankings kept, PII + tokens stripped
    doc = tref.get().to_dict() or {}
    assert doc["name"] == "Deleted Player", doc
    assert doc["profileUrl"] is None
    assert doc["isDeleted"] is True and "deletedAt" in doc
    assert doc["rankings"]["padel"]["pts"] == 1200
    for stripped in ("email", "phone", "preferences", "deviceTokens"):
        assert stripped not in doc, stripped

    # 5. no cascade: match doc untouched
    assert db.collection("matches").document(MATCH_ID).get().exists

    # 6. opponent rivalry against deleted uid -> 200 as "Deleted Player"
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(uid=OPPONENT, email=None)
    rv = client.get(f"/me/lab/rivalry/{TARGET}", params={"sport": "padel"})
    assert rv.status_code == 200, rv.text
    body = rv.json()
    assert body["opponent"]["uid"] == TARGET
    assert body["opponent"]["name"] == "Deleted Player", body
    assert body["head_to_head"]["total_matches"] == 1, body

    # 7. re-delete when Auth user already gone -> still 204 (idempotent)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(uid=TARGET, email=None)
    import firebase_admin.auth as firebase_auth  # type: ignore[import-untyped]

    class GoneAuthAdmin:
        def delete_user(self, uid: str) -> None:
            raise firebase_auth.UserNotFoundError("already gone")

    app.dependency_overrides[get_auth_admin] = lambda: GoneAuthAdmin()
    r = client.request("DELETE", "/me/account")
    assert r.status_code == 204, r.text

    print("account deletion flow OK")
finally:
    cleanup()
    app.dependency_overrides = {}
PY

run_check "account deletion + auth-dependency unit suites pass" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$VENV/bin/pytest" \
  tests/unit/routers/test_account.py \
  tests/unit/test_auth_dependency.py \
  -q

run_check "contract docs cover DELETE /me/account" grep -q "DELETE /me/account" docs/api/contracts.md
run_check "docs describe single destructive Auth op (no separate revoke)" \
  grep -q "not.*revoked separately" docs/data/data-dictionary.md
run_check "data dictionary documents tombstone flag" grep -q "isDeleted" docs/data/data-dictionary.md

echo ""
echo "Smoke tests PR #369: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #369."
