#!/usr/bin/env bash
# Smoke tests for PR #370 - PATCH /me/clubhouse/profile (ACCT-2, #364)
#
# Exercises the profile edit endpoint against the Firestore emulator through
# the FastAPI app: partial updates of display_name/avatar_url/area/levels,
# nameLower kept in lockstep with a rename, per-sport levels MERGE (not a
# map replace), rankings.* left byte-identical to what was seeded, empty
# body -> 400, and 422 for unknown area / non-https avatar / invalid level.
#
# Prereqs:
#   - Firestore emulator running on the configured port.
#
# Usage:
#   bash tests/smoke/pr-370.sh

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

echo "PR #370 PATCH /me/clubhouse/profile smoke"

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

run_check "profile PATCH end-to-end via API" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" - <<'PY'
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.cloud import firestore

import app.repos.region_config_repo as region_config_module
from app.dependencies.repos import get_region_config_repo, get_users_repo
from app.deps import get_current_user
from app.main import app
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

UID = "pr370-profile-target"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])

RANKINGS_SEED = {
    "tennis": {
        "sport": "tennis",
        "pts": 1500,
        "tier": "amateur",
        "registrationTier": "amateur",
        "globalRanking": None,
        "lastUpdated": None,
        "personalBest": 1500,
        "currentStreak": 2,
        "bestStreak": 3,
    }
}


def cleanup() -> None:
    db.collection("users").document(UID).delete()
    db.collection("config").document("regions").delete()
    region_config_module._cache = None
    region_config_module._cache_ts = 0.0


def seed() -> None:
    db.collection("users").document(UID).set(
        {
            "uid": UID,
            "name": "Original Name",
            "nameLower": "original name",
            "email": "pr370@example.com",
            "profileUrl": None,
            "preferences": {
                "area": 101,
                "levels": {"tennis": "beginner", "padel": "advanced"},
                "sports": ["tennis", "padel"],
                "feedOptOut": False,
            },
            "rankings": RANKINGS_SEED,
        }
    )
    db.collection("config").document("regions").set(
        {"mapping": {"101": "athens", "202": "thessaloniki"}, "version": 1}
    )


cleanup()
seed()
app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
app.dependency_overrides[get_region_config_repo] = lambda: RegionConfigRepo(db)
app.dependency_overrides[get_current_user] = lambda: CurrentUser(uid=UID, email=None)
client = TestClient(app)

try:
    # 1. rename + area change -> 200, refreshed response, nameLower in lockstep
    r = client.patch(
        "/me/clubhouse/profile",
        json={"display_name": "Renamed Player", "area": 202},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Renamed Player", body

    doc = db.collection("users").document(UID).get().to_dict() or {}
    assert doc["name"] == "Renamed Player", doc
    assert doc["nameLower"] == "renamed player", doc
    assert doc["preferences"]["area"] == 202, doc
    assert doc["email"] == "pr370@example.com"  # untouched
    assert doc["preferences"]["sports"] == ["tennis", "padel"]  # untouched

    # 2. per-sport levels MERGE: update tennis only, padel must survive untouched
    r = client.patch("/me/clubhouse/profile", json={"levels": {"tennis": "advanced"}})
    assert r.status_code == 200, r.text
    doc = db.collection("users").document(UID).get().to_dict() or {}
    assert doc["preferences"]["levels"]["tennis"] == "advanced", doc
    assert doc["preferences"]["levels"]["padel"] == "advanced", doc  # untouched by merge

    # 3. rankings.* must be byte-identical to what was seeded (levels never reseed pts)
    assert doc["rankings"] == RANKINGS_SEED, doc["rankings"]

    # 4. empty body -> 400 (not 422 - distinguishes "nothing to update")
    r = client.patch("/me/clubhouse/profile", json={})
    assert r.status_code == 400, r.text

    # 5. unknown area -> 422
    r = client.patch("/me/clubhouse/profile", json={"area": 999})
    assert r.status_code == 422, r.text

    # 6. non-https avatar_url -> 422 (HttpUrl type alone accepts http://, needs validator)
    r = client.patch("/me/clubhouse/profile", json={"avatar_url": "http://x.com/a.png"})
    assert r.status_code == 422, r.text

    # 7. invalid level enum value -> 422
    r = client.patch("/me/clubhouse/profile", json={"levels": {"padel": "expert"}})
    assert r.status_code == 422, r.text

    # 8. unknown top-level field rejected (extra="forbid") -> 422
    r = client.patch("/me/clubhouse/profile", json={"nickname": "x"})
    assert r.status_code == 422, r.text

    print("PATCH /me/clubhouse/profile flow OK")
finally:
    cleanup()
    app.dependency_overrides = {}
PY

run_check "clubhouse router + service unit suites pass" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$VENV/bin/pytest" \
  tests/unit/routers/test_clubhouse_router.py \
  tests/unit/services/test_clubhouse_service.py \
  -q

run_check "contract docs cover PATCH /me/clubhouse/profile" grep -q "PATCH /me/clubhouse/profile" docs/api/contracts.md
run_check "docs describe display-name eventual consistency" \
  grep -qi "eventual" docs/api/contracts.md
run_check "endpoints doc covers both GET and PATCH clubhouse profile" \
  grep -c "me/clubhouse/profile" docs/api/endpoints.md | grep -q "^[2-9]"

echo ""
echo "Smoke tests PR #370: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #370."
