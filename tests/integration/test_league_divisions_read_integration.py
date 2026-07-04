from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import (
    get_divisions_repo,
    get_league_service,
    get_leagues_repo,
    get_matches_repo,
)
from app.deps import get_current_user, get_role_service
from app.main import app
from app.repos.divisions_repo import DivisionsRepo
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService
from app.services.role_service import RoleService

pytestmark = [pytest.mark.integration]

_LEAGUE_ID = "test-division-read-surface"
_PENDING_LEAGUE_ID = "test-division-read-pending"
_UID = "division-reader"
_MATCH_IDS = [
    "test-division-upcoming-div1",
    "test-division-upcoming-div2",
    "test-division-completed-div1",
    "test-division-completed-div2",
]


def _restore(previous: dict) -> None:
    app.dependency_overrides = previous


def _cleanup(db) -> None:
    for match_id in _MATCH_IDS:
        db.collection("matches").document(match_id).delete()
    for league_id in (_LEAGUE_ID, _PENDING_LEAGUE_ID):
        league_ref = db.collection("leagues").document(league_id)
        for doc in league_ref.collection("members").stream():
            doc.reference.delete()
        for doc in league_ref.collection("divisions").stream():
            doc.reference.delete()
        league_ref.delete()
    db.collection("users").document(_UID).delete()


def _member_doc(wins: int, losses: int, division_id: str | None) -> dict:
    return {
        "role": "player",
        "status": "active",
        "joinedAt": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "stats": {"wins": wins, "losses": losses},
        "divisionId": division_id,
    }


def _match_doc(match_id: str, status: str, division_id: str) -> dict:
    scheduled_at = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc)
    return {
        "sport": "padel",
        "status": status,
        "matchType": "singles",
        "scheduledAt": scheduled_at if status == "scheduled" else None,
        "finishedAt": finished_at if status == "completed" else None,
        "leagueId": _LEAGUE_ID,
        "divisionId": division_id,
        "participantUids": [f"{match_id}_a", f"{match_id}_b"],
        "participants": [
            {"uid": f"{match_id}_a", "role": "player"},
            {"uid": f"{match_id}_b", "role": "player"},
        ],
    }


def _seed_divided_league(db) -> None:
    db.collection("users").document(_UID).set({"name": "Division Reader"})
    league_ref = db.collection("leagues").document(_LEAGUE_ID)
    league_ref.set(
        {
            "name": "Division Read League",
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
    league_ref.collection("members").document(_UID).set(_member_doc(4, 0, "div-1"))
    league_ref.collection("members").document("division-low").set(
        _member_doc(1, 2, "div-1")
    )
    league_ref.collection("members").document("division-other").set(
        _member_doc(9, 0, "div-2")
    )

    pending_ref = db.collection("leagues").document(_PENDING_LEAGUE_ID)
    pending_ref.set(
        {
            "name": "Pending Division League",
            "sport": "padel",
            "status": "open",
            "ownerUid": "owner",
        }
    )
    pending_ref.collection("members").document(_UID).set(_member_doc(0, 0, None))

    db.collection("matches").document("test-division-upcoming-div1").set(
        _match_doc("test-division-upcoming-div1", "scheduled", "div-1")
    )
    db.collection("matches").document("test-division-upcoming-div2").set(
        _match_doc("test-division-upcoming-div2", "scheduled", "div-2")
    )
    db.collection("matches").document("test-division-completed-div1").set(
        _match_doc("test-division-completed-div1", "completed", "div-1")
    )
    db.collection("matches").document("test-division-completed-div2").set(
        _match_doc("test-division-completed-div2", "completed", "div-2")
    )


def test_division_read_endpoints_filter_flat_pool_and_matches(db) -> None:
    _cleanup(db)
    _seed_divided_league(db)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email="reader@gsm.local"
    )
    app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
    app.dependency_overrides[get_divisions_repo] = lambda: DivisionsRepo(db)
    app.dependency_overrides[get_matches_repo] = lambda: MatchesRepo(db)
    app.dependency_overrides[get_league_service] = lambda: LeagueService(
        LeaguesRepo(db), db, divisions_repo=DivisionsRepo(db)
    )
    app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
    client = TestClient(app)

    try:
        divisions_resp = client.get(f"/leagues/{_LEAGUE_ID}/divisions")
        assert divisions_resp.status_code == 200
        assert [
            division["division_id"] for division in divisions_resp.json()["divisions"]
        ] == ["div-1", "div-2"]

        standings_resp = client.get(f"/leagues/{_LEAGUE_ID}/divisions/div-1/standings")
        assert standings_resp.status_code == 200
        assert [entry["uid"] for entry in standings_resp.json()["standings"]] == [
            _UID,
            "division-low",
        ]

        upcoming_resp = client.get(f"/leagues/{_LEAGUE_ID}/divisions/div-1/matches")
        assert upcoming_resp.status_code == 200
        assert [match["match_id"] for match in upcoming_resp.json()["matches"]] == [
            "test-division-upcoming-div1"
        ]

        completed_resp = client.get(
            f"/leagues/{_LEAGUE_ID}/divisions/div-1/matches",
            params={"type": "completed"},
        )
        assert completed_resp.status_code == 200
        assert [match["match_id"] for match in completed_resp.json()["matches"]] == [
            "test-division-completed-div1"
        ]

        unknown_resp = client.get(f"/leagues/{_LEAGUE_ID}/divisions/nope/standings")
        assert unknown_resp.status_code == 404

        pending_resp = client.get(f"/leagues/{_PENDING_LEAGUE_ID}/divisions")
        assert pending_resp.status_code == 409
        assert pending_resp.json()["detail"] == "league not yet divided"
    finally:
        _cleanup(db)
        _restore(previous)
