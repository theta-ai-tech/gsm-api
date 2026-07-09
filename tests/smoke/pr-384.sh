#!/usr/bin/env bash
# Smoke tests for PR #384 - expose area + levels in GET /me/clubhouse/profile (#382)
#
# Verifies the additive fields on ClubhouseProfileResponse:
#   - GET /me/clubhouse/profile returns area (int) and levels (per-sport map)
#     sourced from preferences, with real seeded values (not model defaults).
#   - PATCH /me/clubhouse/profile then GET reflects the new area/levels, with
#     per-sport levels merge (an unmentioned sport keeps its level).
#   - Existing fields (uid/display_name/avatar_url/resume) unchanged.
#
# Prereqs:
#   - Firestore emulator running on the configured port.
#
# Usage:
#   bash tests/smoke/pr-384.sh

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

echo "PR #384 GET/PATCH /me/clubhouse/profile area+levels smoke"

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

run_check "area+levels round-trip via API" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" \
  "$VENV/bin/python" - <<'PY'
import os

from fastapi.testclient import TestClient
from google.cloud import firestore

import app.repos.region_config_repo as region_config_module
from app.dependencies.repos import get_region_config_repo, get_users_repo
from app.deps import get_current_user
from app.main import app
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

UID = "pr384-profile-target"

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
            "name": "Prefill Target",
            "nameLower": "prefill target",
            "email": "pr384@example.com",
            "profileUrl": None,
            "preferences": {
                "area": 101,
                "levels": {"tennis": "advanced", "padel": "beginner"},
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
    # 1. GET returns seeded area + levels from preferences (real values, not defaults)
    r = client.get("/me/clubhouse/profile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["area"] == 101, body
    assert body["levels"] == {
        "tennis": "advanced",
        "padel": "beginner",
        "pickleball": None,
    }, body
    # existing fields unchanged
    assert body["uid"] == UID, body
    assert body["display_name"] == "Prefill Target", body
    assert "resume" in body, body

    # 2. PATCH area + padel level (per-sport merge), tennis must survive
    r = client.patch(
        "/me/clubhouse/profile",
        json={"area": 202, "levels": {"padel": "intermediate"}},
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["area"] == 202, patched
    assert patched["levels"]["padel"] == "intermediate", patched
    assert patched["levels"]["tennis"] == "advanced", patched

    # 3. GET reflects the applied change
    r = client.get("/me/clubhouse/profile")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["area"] == 202, got
    assert got["levels"]["padel"] == "intermediate", got
    assert got["levels"]["tennis"] == "advanced", got

    print("GET/PATCH area+levels round-trip OK")
finally:
    cleanup()
    app.dependency_overrides = {}
PY

run_check "clubhouse router unit suite passes" env \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$VENV/bin/pytest" \
  tests/unit/routers/test_clubhouse_router.py \
  -q

run_check "endpoints doc mentions area prefill" \
  grep -qi "prefill" docs/api/endpoints.md

echo ""
echo "Smoke tests PR #384: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #384."
