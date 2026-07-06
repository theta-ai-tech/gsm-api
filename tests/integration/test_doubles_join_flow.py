"""End-to-end doubles team join flow against the Firestore emulator.

Covers issue #366: invite → accept/decline → kickoff (team seeding) → team
standings, plus GET /players prefix search over the seeded users.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_league_service, get_leagues_repo, get_users_repo
from app.deps import get_current_user, get_role_service
from app.main import app
from app.repos.leagues_repo import LeaguesRepo
from app.repos.notification_intent_repo import NotificationIntentRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService
from app.services.role_service import RoleService

pytestmark = [pytest.mark.integration]

_LEAGUE_ID = "test-doubles-join-flow"

# (uid, name, padel pts) — "zdbl" prefix keeps player search isolated from other seeds.
_USERS = [
    ("zdbl-cap1", "Zdbl Capone", 1500),
    ("zdbl-par1", "Zdbl Parone", 1300),
    ("zdbl-cap2", "Zdbl Captwo", 900),
    ("zdbl-par2", "Zdbl Partwo", 700),
    ("zdbl-cap3", "Zdbl Capthree", 600),
    ("zdbl-par3", "Zdbl Parthree", 500),
]


class _Auth:
    """Mutable holder so tests can switch the authenticated user mid-flow."""

    def __init__(self) -> None:
        self.uid = _USERS[0][0]

    def __call__(self) -> CurrentUser:
        return CurrentUser(uid=self.uid, email=f"{self.uid}@gsm.local")


def _cleanup(db) -> None:
    league_ref = db.collection("leagues").document(_LEAGUE_ID)
    for sub in ("members", "teams", "divisions"):
        for doc in league_ref.collection(sub).stream():
            doc.reference.delete()
    league_ref.delete()
    for uid, _name, _pts in _USERS:
        for doc in (
            db.collection("users")
            .document(uid)
            .collection("notificationIntents")
            .stream()
        ):
            doc.reference.delete()
        db.collection("users").document(uid).delete()


def _seed(db) -> None:
    db.collection("leagues").document(_LEAGUE_ID).set(
        {
            "name": "Doubles Join Flow Test",
            "sport": "padel",
            "status": "open",
            "format": "doubles",
            "ownerUid": _USERS[0][0],
            "region": "athens",
            "maxPlayers": 8,
            "currentPlayers": 0,
            "startDate": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "divisionConfig": {"targetSize": 6, "maxDivisions": None},
        }
    )
    for uid, name, pts in _USERS:
        db.collection("users").document(uid).set(
            {
                "uid": uid,
                "name": name,
                "nameLower": name.lower(),
                "rankings": {"padel": {"pts": pts}},
            }
        )


@pytest.fixture
def doubles_client(db):
    _cleanup(db)
    _seed(db)
    auth = _Auth()
    prev = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = auth
    app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
    app.dependency_overrides[get_league_service] = lambda: LeagueService(
        LeaguesRepo(db), db, notification_intent_repo=NotificationIntentRepo(db)
    )
    app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
    client = TestClient(app)
    try:
        yield client, auth, db
    finally:
        _cleanup(db)
        app.dependency_overrides = prev


def _invite(client: TestClient, auth: _Auth, captain: str, partner: str) -> dict:
    auth.uid = captain
    resp = client.post(f"/leagues/{_LEAGUE_ID}/join", json={"partner_uid": partner})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _accept(client: TestClient, auth: _Auth, partner: str, team_id: str) -> dict:
    auth.uid = partner
    resp = client.post(f"/leagues/{_LEAGUE_ID}/teams/{team_id}/accept")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_doubles_full_flow(doubles_client) -> None:
    client, auth, db = doubles_client
    league_ref = db.collection("leagues").document(_LEAGUE_ID)

    # --- invite: pending team, no members, no capacity ---
    team1 = _invite(client, auth, "zdbl-cap1", "zdbl-par1")
    assert team1["status"] == "pending"
    assert team1["captain_uid"] == "zdbl-cap1"
    assert team1["partner_uid"] == "zdbl-par1"
    assert league_ref.get().to_dict()["currentPlayers"] == 0
    assert not list(league_ref.collection("members").stream())

    # Partner got a push intent.
    intents = [
        doc.to_dict()
        for doc in db.collection("users")
        .document("zdbl-par1")
        .collection("notificationIntents")
        .stream()
    ]
    assert any(i["type"] == "league_team_invite" for i in intents)

    # Invite surfaces on the partner's "mine" list.
    auth.uid = "zdbl-par1"
    resp = client.get(f"/leagues/{_LEAGUE_ID}/teams?mine=true")
    assert resp.status_code == 200
    assert [t["team_id"] for t in resp.json()["teams"]] == [team1["team_id"]]

    # Wrong actor cannot accept.
    auth.uid = "zdbl-cap2"
    resp = client.post(f"/leagues/{_LEAGUE_ID}/teams/{team1['team_id']}/accept")
    assert resp.status_code == 403

    # --- accept: team active, both members exist, capacity +2 ---
    accepted = _accept(client, auth, "zdbl-par1", team1["team_id"])
    assert accepted["status"] == "active"
    assert league_ref.get().to_dict()["currentPlayers"] == 2
    members = {
        doc.id: doc.to_dict() for doc in league_ref.collection("members").stream()
    }
    assert set(members) == {"zdbl-cap1", "zdbl-par1"}
    assert members["zdbl-cap1"]["teamId"] == team1["team_id"]
    assert members["zdbl-cap1"]["partnerUid"] == "zdbl-par1"
    assert members["zdbl-cap1"]["uid"] == "zdbl-cap1"

    # Double-accept conflicts.
    resp = client.post(f"/leagues/{_LEAGUE_ID}/teams/{team1['team_id']}/accept")
    assert resp.status_code == 409

    # A teamed user cannot start another team.
    auth.uid = "zdbl-cap1"
    resp = client.post(f"/leagues/{_LEAGUE_ID}/join", json={"partner_uid": "zdbl-cap3"})
    assert resp.status_code == 409

    # Doubles join without a partner is a validation error.
    resp = client.post(f"/leagues/{_LEAGUE_ID}/join")
    assert resp.status_code == 400

    # --- second team + a declined invite ---
    team2 = _invite(client, auth, "zdbl-cap2", "zdbl-par2")
    _accept(client, auth, "zdbl-par2", team2["team_id"])
    assert league_ref.get().to_dict()["currentPlayers"] == 4

    team3 = _invite(client, auth, "zdbl-cap3", "zdbl-par3")
    auth.uid = "zdbl-par3"
    resp = client.post(f"/leagues/{_LEAGUE_ID}/teams/{team3['team_id']}/decline")
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"
    assert league_ref.get().to_dict()["currentPlayers"] == 4

    # --- kickoff: 2 active teams → 1 division, teammates together ---
    auth.uid = "zdbl-cap1"  # league owner
    resp = client.post(f"/leagues/{_LEAGUE_ID}/kickoff")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["division_count"] == 1
    assert body["divisions"][0]["current_players"] == 4
    # Team averages: team1 (1500+1300)//2=1400, team2 (900+700)//2=800.
    assert body["divisions"][0]["rating_range"] == {"min": 800, "max": 1400}

    teams = {doc.id: doc.to_dict() for doc in league_ref.collection("teams").stream()}
    assert teams[team1["team_id"]]["divisionId"] == "div-1"
    assert teams[team2["team_id"]]["divisionId"] == "div-1"
    assert teams[team3["team_id"]].get("divisionId") is None  # declined: not seeded
    members = {
        doc.id: doc.to_dict() for doc in league_ref.collection("members").stream()
    }
    assert all(m["divisionId"] == "div-1" for m in members.values())

    # --- standings: team rows ---
    resp = client.get(f"/leagues/{_LEAGUE_ID}/standings")
    assert resp.status_code == 200, resp.text
    standings = resp.json()["standings"]
    assert len(standings) == 2  # 2 teams, not 4 players
    row_teams = {row["team_id"] for row in standings}
    assert row_teams == {team1["team_id"], team2["team_id"]}
    for row in standings:
        assert len(row["member_uids"]) == 2
        assert " / " in row["display_name"]

    resp = client.get(f"/leagues/{_LEAGUE_ID}/divisions/div-1/standings")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["standings"]) == 2


def test_players_prefix_search(doubles_client) -> None:
    client, auth, _db = doubles_client
    auth.uid = "zdbl-cap1"

    resp = client.get("/players?search=zdbl&sport=padel&limit=10")
    assert resp.status_code == 200, resp.text
    players = resp.json()["players"]
    uids = [p["uid"] for p in players]
    # Prefix match over the seeded names; the caller is excluded.
    assert "zdbl-cap1" not in uids
    assert {"zdbl-par1", "zdbl-cap2", "zdbl-par2"} <= set(uids)
    by_uid = {p["uid"]: p for p in players}
    assert by_uid["zdbl-par1"]["pts"] == 1300

    # Prefix, not substring: "capone" does not match "Zdbl Capone".
    resp = client.get("/players?search=capone")
    assert resp.status_code == 200
    assert all(p["uid"].startswith("zdbl") is False for p in resp.json()["players"])

    # Missing search param → validation error.
    resp = client.get("/players")
    assert resp.status_code == 422
