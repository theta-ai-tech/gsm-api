from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_users_repo
from app.deps import get_current_user
from app.main import app
from app.models.common import (
    PerSportRankings,
    SportRanking,
    UserCompletedMatchSummary,
)
from app.models.enums import MatchResultEnum, SportEnum, TierEnum
from app.models.user import PrivateUserProfile
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest.fixture
def mock_users_repo():
    return Mock(spec=UsersRepo)


@pytest.fixture
def mock_current_user():
    return CurrentUser(uid="test_user", email="test@example.com")


@pytest.fixture
def client(mock_users_repo, mock_current_user):
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_users_repo] = lambda: mock_users_repo
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


def _make_profile(
    uid: str = "test_user",
    name: str = "Test User",
    profile_url: str | None = None,
    rankings: PerSportRankings | None = None,
    completed_matches: list[UserCompletedMatchSummary] | None = None,
    leagues_completed: list | None = None,
) -> PrivateUserProfile:
    from app.models.common import PerSportLevels, UserPreferences

    return PrivateUserProfile(
        uid=uid,
        name=name,
        email="test@example.com",
        profile_url=profile_url,
        rankings=rankings or PerSportRankings(),
        preferences=UserPreferences(
            area=101,
            levels=PerSportLevels(),
            sports=[],
        ),
        leagues_active=[],
        leagues_completed=leagues_completed or [],
        upcoming_matches=[],
        completed_matches=completed_matches or [],
        journal_recent=[],
    )


class TestGetClubhouseProfile:
    def test_returns_200_with_rankings(self, client, mock_users_repo):
        profile = _make_profile(
            rankings=PerSportRankings(
                tennis=SportRanking(
                    sport=SportEnum.TENNIS,
                    pts=820,
                    global_ranking=340,
                    tier=TierEnum.AMATEUR,
                    personal_best=850,
                    current_streak=3,
                    best_streak=5,
                ),
                padel=SportRanking(
                    sport=SportEnum.PADEL,
                    pts=600,
                    tier=TierEnum.INTERMEDIATE,
                ),
            ),
            completed_matches=[
                UserCompletedMatchSummary(
                    match_id="m1",
                    sport=SportEnum.TENNIS,
                    finished_at=_utc(2026, 1, 10),
                    result=MatchResultEnum.WIN,
                ),
                UserCompletedMatchSummary(
                    match_id="m2",
                    sport=SportEnum.TENNIS,
                    finished_at=_utc(2026, 1, 15),
                    result=MatchResultEnum.LOSS,
                ),
            ],
        )
        mock_users_repo.get_private_profile.return_value = profile

        resp = client.get("/me/clubhouse/profile")

        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"] == "test_user"
        assert data["display_name"] == "Test User"
        assert data["avatar_url"] is None

        resume = data["resume"]
        # TODO: totals return 0 until uncapped counter fields are added
        assert resume["total_matches"] == 0
        assert resume["total_wins"] == 0
        assert resume["leagues_completed"] == 0
        assert len(resume["sports"]) == 2

        tennis = next(s for s in resume["sports"] if s["sport"] == "tennis")
        assert tennis["pts"] == 820
        assert tennis["tier"] == "amateur"
        assert tennis["global_ranking"] == 340
        assert tennis["personal_best"] == 850
        assert tennis["current_streak"] == 3
        assert tennis["best_streak"] == 5

        padel = next(s for s in resume["sports"] if s["sport"] == "padel")
        assert padel["pts"] == 600
        assert padel["tier"] == "intermediate"

    def test_new_user_empty_data(self, client, mock_users_repo):
        profile = _make_profile()
        mock_users_repo.get_private_profile.return_value = profile

        resp = client.get("/me/clubhouse/profile")

        assert resp.status_code == 200
        data = resp.json()
        resume = data["resume"]
        assert resume["total_matches"] == 0
        assert resume["total_wins"] == 0
        assert resume["leagues_completed"] == 0
        assert resume["sports"] == []

    def test_user_not_found_returns_404(self, client, mock_users_repo):
        mock_users_repo.get_private_profile.return_value = None

        resp = client.get("/me/clubhouse/profile")

        assert resp.status_code == 404

    def test_profile_url_returned_as_avatar(self, client, mock_users_repo):
        profile = _make_profile(profile_url="http://example.com/avatar.png")
        mock_users_repo.get_private_profile.return_value = profile

        resp = client.get("/me/clubhouse/profile")

        assert resp.status_code == 200
        assert resp.json()["avatar_url"] == "http://example.com/avatar.png"

    def test_leagues_completed_counted(self, client, mock_users_repo):
        from app.models.common import LeagueSummary
        from app.models.enums import LeagueStatusEnum

        profile = _make_profile(
            leagues_completed=[
                LeagueSummary(
                    league_id="l1",
                    name="League 1",
                    sport=SportEnum.TENNIS,
                    status=LeagueStatusEnum.COMPLETED,
                ),
                LeagueSummary(
                    league_id="l2",
                    name="League 2",
                    sport=SportEnum.PADEL,
                    status=LeagueStatusEnum.COMPLETED,
                ),
            ],
        )
        mock_users_repo.get_private_profile.return_value = profile

        resp = client.get("/me/clubhouse/profile")

        assert resp.status_code == 200
        # TODO: returns 0 until uncapped counter field is added to user doc
        assert resp.json()["resume"]["leagues_completed"] == 0


class TestClubhouseAuthRequired:
    def test_no_auth_returns_401(self):
        previous_overrides = dict(app.dependency_overrides)
        # Remove auth override so real auth kicks in
        app.dependency_overrides.pop(get_current_user, None)
        try:
            test_client = TestClient(app)
            resp = test_client.get("/me/clubhouse/profile")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides = previous_overrides
