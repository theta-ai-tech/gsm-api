"""
Integration tests for LG-15: league browse, join, standings, and matches
endpoints against the Firestore emulator.

Endpoints under test:
  GET  /leagues
  GET  /leagues/{leagueId}
  GET  /leagues/{leagueId}/standings
  POST /leagues/{leagueId}/join
  GET  /leagues/{leagueId}/matches

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via ``make emu-all``)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import (
    get_league_service,
    get_leagues_repo,
    get_matches_repo,
)
from app.deps import get_current_user, get_role_service
from app.main import app
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService
from app.services.role_service import RoleService
from tools.seed_data import PRIMARY_USER_UID

pytestmark = [pytest.mark.integration]

_NON_MEMBER_UID = "int_test_non_member"


def _restore(previous: dict) -> None:
    app.dependency_overrides = previous


# ---------------------------------------------------------------------------
# GET /leagues — browse with filters
# ---------------------------------------------------------------------------


@pytest.mark.seeded
class TestGetLeagues:
    @pytest.fixture(autouse=True)
    def _client(self, seeded_firestore):
        db = seeded_firestore
        prev = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=PRIMARY_USER_UID, email="test@gsm.local"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
        self.client = TestClient(app)
        yield
        _restore(prev)

    def test_no_filters_returns_open_leagues(self):
        resp = self.client.get("/leagues")
        assert resp.status_code == 200
        body = resp.json()
        ids = [lg["league_id"] for lg in body["leagues"]]
        assert "tennis-local-2025" in ids  # only OPEN league in seed

    def test_region_filter_athens(self):
        resp = self.client.get(
            "/leagues", params={"region": "athens", "status": "active"}
        )
        assert resp.status_code == 200
        ids = [lg["league_id"] for lg in resp.json()["leagues"]]
        assert "padel-local-2025" in ids
        for lg in resp.json()["leagues"]:
            assert lg["region"] == "athens"

    def test_status_open_filter(self):
        resp = self.client.get("/leagues", params={"status": "open"})
        assert resp.status_code == 200
        for lg in resp.json()["leagues"]:
            assert lg["status"] == "open"

    def test_sport_padel_filter(self):
        resp = self.client.get(
            "/leagues", params={"sport": "padel", "status": "active"}
        )
        assert resp.status_code == 200
        for lg in resp.json()["leagues"]:
            assert lg["sport"] == "padel"

    def test_empty_result_returns_200_not_404(self):
        resp = self.client.get("/leagues", params={"region": "no-such-region"})
        assert resp.status_code == 200
        assert resp.json() == {"leagues": [], "next_cursor": None}


# ---------------------------------------------------------------------------
# GET /leagues/{leagueId} — detail view
# ---------------------------------------------------------------------------


@pytest.mark.seeded
class TestGetLeagueDetail:
    @pytest.fixture(autouse=True)
    def _client(self, seeded_firestore):
        db = seeded_firestore
        prev = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=PRIMARY_USER_UID, email="test@gsm.local"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
        self.client = TestClient(app)
        yield
        _restore(prev)

    def test_known_league_returns_200(self):
        resp = self.client.get("/leagues/padel-local-2025")
        assert resp.status_code == 200
        body = resp.json()
        assert body["league_id"] == "padel-local-2025"
        assert body["name"] == "Local Padel Ladder 2025"

    def test_response_includes_all_league_fields(self):
        resp = self.client.get("/leagues/padel-local-2025")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sport"] == "padel"
        assert body["region"] == "athens"
        assert body["status"] == "active"
        assert body["max_players"] == 12
        assert body["current_players"] == 4
        assert body["owner_uid"] == "user_ignatios"
        assert body["start_date"] is not None
        assert body["season"] == "Autumn 2025"

    def test_unknown_league_returns_404(self):
        resp = self.client.get("/leagues/nonexistent-league-xyz")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "League not found"


# ---------------------------------------------------------------------------
# GET /leagues/{leagueId}/standings
# ---------------------------------------------------------------------------


@pytest.mark.seeded
class TestGetLeagueStandings:
    @pytest.fixture(autouse=True)
    def _client(self, seeded_firestore):
        db = seeded_firestore
        prev = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=PRIMARY_USER_UID, email="test@gsm.local"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
        app.dependency_overrides[get_league_service] = lambda: LeagueService(
            LeaguesRepo(db), db
        )
        app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
        self.client = TestClient(app)
        self.db = db
        self.prev = prev
        yield
        _restore(prev)

    def test_returns_ranked_member_list(self):
        resp = self.client.get("/leagues/padel-local-2025/standings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["league_id"] == "padel-local-2025"
        standings = body["standings"]
        assert len(standings) == 4  # user_ignatios, user_alice, user_bob, user_diana
        for entry in standings:
            assert set(entry.keys()) == {
                "rank",
                "uid",
                "display_name",
                "wins",
                "losses",
                "tier_ring",
            }
        # All members have stats=None → wins=0, losses=0 → all rank 1
        assert all(e["rank"] == 1 for e in standings)

    def test_non_member_returns_403(self):
        _restore(self.prev)
        prev2 = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=_NON_MEMBER_UID, email="nonmember@gsm.local"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(self.db)
        app.dependency_overrides[get_role_service] = lambda: RoleService(db=self.db)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/leagues/padel-local-2025/standings")
        assert resp.status_code == 403
        _restore(prev2)

    def test_unknown_league_returns_404(self):
        resp = self.client.get("/leagues/nonexistent-league-xyz/standings")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "League not found"


# ---------------------------------------------------------------------------
# POST /leagues/{leagueId}/join
# ---------------------------------------------------------------------------


class TestPostLeagueJoin:
    _HAPPY_LEAGUE_ID = "test-int-join-happy"
    _FULL_LEAGUE_ID = "test-int-join-full"
    _DUPE_LEAGUE_ID = "test-int-join-dupe"

    def _make_open_league_doc(
        self, max_players: int = 10, current_players: int = 0
    ) -> dict:
        return {
            "name": "Test Join League",
            "sport": "padel",
            "status": "open",
            "ownerUid": "owner_test",
            "region": "test-region",
            "maxPlayers": max_players,
            "currentPlayers": current_players,
            "startDate": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "endDate": datetime(2026, 10, 31, tzinfo=timezone.utc),
            "tier": "intermediate",
        }

    def _setup_client(self, db) -> tuple[TestClient, dict]:
        prev = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=PRIMARY_USER_UID, email="test@gsm.local"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
        app.dependency_overrides[get_league_service] = lambda: LeagueService(
            LeaguesRepo(db), db
        )
        app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
        return TestClient(app), prev

    def _cleanup_league(self, db, league_id: str) -> None:
        for doc in (
            db.collection("leagues").document(league_id).collection("members").stream()
        ):
            doc.reference.delete()
        db.collection("leagues").document(league_id).delete()

    def test_happy_path_returns_201_and_creates_member(self, db):
        db.collection("leagues").document(self._HAPPY_LEAGUE_ID).set(
            self._make_open_league_doc(max_players=10, current_players=0)
        )
        client, prev = self._setup_client(db)
        try:
            resp = client.post(f"/leagues/{self._HAPPY_LEAGUE_ID}/join")
            assert resp.status_code == 201
            body = resp.json()
            assert body["uid"] == PRIMARY_USER_UID
            assert body["role"] == "player"
            assert body["status"] == "active"
            assert body["stats"] is None
            # Verify member doc written to Firestore
            member_doc = (
                db.collection("leagues")
                .document(self._HAPPY_LEAGUE_ID)
                .collection("members")
                .document(PRIMARY_USER_UID)
                .get()
            )
            assert member_doc.exists
            # Verify currentPlayers incremented
            league_doc = db.collection("leagues").document(self._HAPPY_LEAGUE_ID).get()
            assert league_doc.to_dict()["currentPlayers"] == 1
        finally:
            self._cleanup_league(db, self._HAPPY_LEAGUE_ID)
            _restore(prev)

    def test_already_member_returns_409(self, db):
        db.collection("leagues").document(self._DUPE_LEAGUE_ID).set(
            self._make_open_league_doc(max_players=10, current_players=1)
        )
        # Pre-seed user as existing member
        (
            db.collection("leagues")
            .document(self._DUPE_LEAGUE_ID)
            .collection("members")
            .document(PRIMARY_USER_UID)
            .set(
                {
                    "role": "player",
                    "status": "active",
                    "joinedAt": datetime.now(timezone.utc),
                }
            )
        )
        client, prev = self._setup_client(db)
        try:
            resp = client.post(f"/leagues/{self._DUPE_LEAGUE_ID}/join")
            assert resp.status_code == 409
        finally:
            self._cleanup_league(db, self._DUPE_LEAGUE_ID)
            _restore(prev)

    def test_league_full_returns_409(self, db):
        db.collection("leagues").document(self._FULL_LEAGUE_ID).set(
            self._make_open_league_doc(max_players=1, current_players=1)
        )
        client, prev = self._setup_client(db)
        try:
            resp = client.post(f"/leagues/{self._FULL_LEAGUE_ID}/join")
            assert resp.status_code == 409
        finally:
            self._cleanup_league(db, self._FULL_LEAGUE_ID)
            _restore(prev)

    def test_join_with_display_name_visible_in_standings(self, db):
        """When a user joins with a display_name, standings should show it instead of uid."""
        _DISPLAY_NAME_LEAGUE_ID = "test-int-join-displayname"
        db.collection("leagues").document(_DISPLAY_NAME_LEAGUE_ID).set(
            self._make_open_league_doc(max_players=10, current_players=0)
        )
        prev = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=PRIMARY_USER_UID, email="test@gsm.local", display_name="Test User"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
        app.dependency_overrides[get_league_service] = lambda: LeagueService(
            LeaguesRepo(db), db
        )
        app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
        client = TestClient(app)
        try:
            # Join the league
            resp = client.post(f"/leagues/{_DISPLAY_NAME_LEAGUE_ID}/join")
            assert resp.status_code == 201
            body = resp.json()
            assert body["display_name"] == "Test User"

            # Verify displayName stored in Firestore member doc
            member_doc = (
                db.collection("leagues")
                .document(_DISPLAY_NAME_LEAGUE_ID)
                .collection("members")
                .document(PRIMARY_USER_UID)
                .get()
            )
            assert member_doc.exists
            assert member_doc.to_dict().get("displayName") == "Test User"

            # Verify standings show real name
            standings_resp = client.get(f"/leagues/{_DISPLAY_NAME_LEAGUE_ID}/standings")
            assert standings_resp.status_code == 200
            standings = standings_resp.json()["standings"]
            assert len(standings) == 1
            assert standings[0]["display_name"] == "Test User"
            assert standings[0]["uid"] == PRIMARY_USER_UID
        finally:
            self._cleanup_league(db, _DISPLAY_NAME_LEAGUE_ID)
            _restore(prev)


# ---------------------------------------------------------------------------
# GET /leagues/{leagueId}/matches
# ---------------------------------------------------------------------------


@pytest.mark.seeded
class TestGetLeagueMatches:
    @pytest.fixture(autouse=True)
    def _client(self, seeded_firestore):
        db = seeded_firestore
        prev = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=PRIMARY_USER_UID, email="test@gsm.local"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
        app.dependency_overrides[get_matches_repo] = lambda: MatchesRepo(db)
        app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)
        self.client = TestClient(app)
        yield
        _restore(prev)

    def test_upcoming_matches(self):
        resp = self.client.get(
            "/leagues/padel-local-2025/matches", params={"type": "upcoming"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "matches" in body
        assert "next_cursor" in body
        match_ids = [m["match_id"] for m in body["matches"]]
        assert "match-upcoming-1" in match_ids
        assert "match-upcoming-2" in match_ids

    def test_completed_matches(self):
        resp = self.client.get(
            "/leagues/padel-local-2025/matches", params={"type": "completed"}
        )
        assert resp.status_code == 200
        body = resp.json()
        match_ids = [m["match_id"] for m in body["matches"]]
        assert "match-completed-1" in match_ids
        assert "match-completed-2" in match_ids
