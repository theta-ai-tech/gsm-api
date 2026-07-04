from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_league_service
from app.deps import get_current_user, get_role_service
from app.main import app
from app.repos.leagues_repo import LeaguesRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService
from app.services.role_service import RoleService

pytestmark = [pytest.mark.integration]

_LEAGUE_ID = "test-kickoff-division-split"
_ADMIN_UID = "kickoff-admin"


def _restore(previous: dict) -> None:
    app.dependency_overrides = previous


def _cleanup_league(db) -> None:
    league_ref = db.collection("leagues").document(_LEAGUE_ID)
    for doc in league_ref.collection("members").stream():
        doc.reference.delete()
    for doc in league_ref.collection("divisions").stream():
        doc.reference.delete()
    league_ref.delete()


def _seed_kickoff_league(db) -> list[tuple[str, int]]:
    ranked_users = [
        (_ADMIN_UID, 1800),
        ("kickoff-u01", 1710),
        ("kickoff-u02", 1620),
        ("kickoff-u03", 1530),
        ("kickoff-u04", 1440),
        ("kickoff-u05", 1350),
        ("kickoff-u06", 1260),
        ("kickoff-u07", 1170),
        ("kickoff-u08", 1080),
        ("kickoff-u09", 990),
        ("kickoff-unranked", 0),
    ]
    league_ref = db.collection("leagues").document(_LEAGUE_ID)
    league_ref.set(
        {
            "name": "Kickoff Test League",
            "sport": "padel",
            "status": "open",
            "ownerUid": _ADMIN_UID,
            "region": "athens",
            "maxPlayers": 12,
            "currentPlayers": len(ranked_users),
            "startDate": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "endDate": datetime(2026, 11, 30, tzinfo=timezone.utc),
            "tier": "intermediate",
            "divisionConfig": {"targetSize": 6, "maxDivisions": None},
        }
    )
    for index, (uid, pts) in enumerate(ranked_users):
        user_doc = {"displayName": uid}
        if pts:
            user_doc["rankings"] = {"padel": {"pts": pts}}
        db.collection("users").document(uid).set(user_doc)
        league_ref.collection("members").document(uid).set(
            {
                "uid": uid,
                "role": "admin" if uid == _ADMIN_UID else "player",
                "status": "active",
                "joinedAt": datetime(2026, 8, index + 1, tzinfo=timezone.utc),
                "stats": None,
            }
        )
    return ranked_users


def test_kickoff_splits_members_and_is_idempotent(db) -> None:
    _cleanup_league(db)
    ranked_users = _seed_kickoff_league(db)
    prev = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_ADMIN_UID, email="admin@gsm.local"
    )
    app.dependency_overrides[get_league_service] = lambda: LeagueService(
        LeaguesRepo(db), db
    )
    app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
    client = TestClient(app)

    try:
        resp = client.post(f"/leagues/{_LEAGUE_ID}/kickoff")
        assert resp.status_code == 200
        body = resp.json()
        assert body["division_count"] == 2
        assert body["division_ids"] == ["div-1", "div-2"]
        assert [division["current_players"] for division in body["divisions"]] == [6, 5]
        assert body["divisions"][0]["rating_range"] == {"min": 1350, "max": 1800}
        assert body["divisions"][1]["rating_range"] == {"min": 0, "max": 1260}

        league_doc = db.collection("leagues").document(_LEAGUE_ID).get().to_dict()
        assert league_doc["status"] == "active"
        assert league_doc["dividedAt"] is not None

        expected_assignments = {
            uid: "div-1" if index < 6 else "div-2"
            for index, (uid, _pts) in enumerate(ranked_users)
        }
        league_ref = db.collection("leagues").document(_LEAGUE_ID)
        assignments = {
            doc.id: doc.to_dict().get("divisionId")
            for doc in league_ref.collection("members").stream()
        }
        assert assignments == expected_assignments

        second_resp = client.post(f"/leagues/{_LEAGUE_ID}/kickoff")
        assert second_resp.status_code == 200
        assert second_resp.json()["already_kicked_off"] is True
        assert len(list(league_ref.collection("divisions").stream())) == 2
        assert {
            doc.id: doc.to_dict().get("divisionId")
            for doc in league_ref.collection("members").stream()
        } == expected_assignments
    finally:
        _cleanup_league(db)
        _restore(prev)
