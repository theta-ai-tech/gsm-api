from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_region_config_repo, get_users_repo
from app.deps import get_current_user
from app.main import app
from app.models.common import (
    PerSportLevels,
    PerSportRankings,
    SportRanking,
    UserCompletedMatchSummary,
)
from app.models.enums import LevelEnum, MatchResultEnum, SportEnum, TierEnum
from app.models.region_config import RegionConfig
from app.models.user import PrivateUserProfile
from app.repos.region_config_repo import RegionConfigRepo
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
    area: int = 101,
    levels: "PerSportLevels | None" = None,
) -> PrivateUserProfile:
    from app.models.common import PerSportLevels, UserPreferences

    return PrivateUserProfile(
        uid=uid,
        name=name,
        email="test@example.com",
        profile_url=profile_url,
        rankings=rankings or PerSportRankings(),
        preferences=UserPreferences(
            area=area,
            levels=levels or PerSportLevels(),
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
        # NOTE: values come from capped cache (completedMatches max 10)
        assert resume["total_matches"] == 2
        assert resume["total_wins"] == 1
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

    def test_returns_area_and_levels_from_preferences(self, client, mock_users_repo):
        profile = _make_profile(
            area=202,
            levels=PerSportLevels(
                tennis=LevelEnum.ADVANCED,
                padel=LevelEnum.INTERMEDIATE,
            ),
        )
        mock_users_repo.get_private_profile.return_value = profile

        resp = client.get("/me/clubhouse/profile")

        assert resp.status_code == 200
        data = resp.json()
        assert data["area"] == 202
        assert data["levels"] == {
            "tennis": "advanced",
            "padel": "intermediate",
            "pickleball": None,
        }

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
        # NOTE: leagues_completed cache is capped at 20
        assert resp.json()["resume"]["leagues_completed"] == 2


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


@pytest.fixture
def mock_region_config_repo():
    repo = Mock(spec=RegionConfigRepo)
    repo.get.return_value = RegionConfig(
        mapping={"101": "athens", "202": "thessaloniki"}, version=1
    )
    return repo


@pytest.fixture
def patch_client(mock_users_repo, mock_current_user, mock_region_config_repo):
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_users_repo] = lambda: mock_users_repo
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    app.dependency_overrides[get_region_config_repo] = lambda: mock_region_config_repo
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


class TestPatchClubhouseProfile:
    def test_patch_display_name_returns_updated_profile(
        self, patch_client, mock_users_repo
    ):
        before = _make_profile(name="Old Name")
        after = _make_profile(name="New Name")
        mock_users_repo.get_private_profile.side_effect = [before, after]

        resp = patch_client.patch(
            "/me/clubhouse/profile", json={"display_name": "New Name"}
        )

        assert resp.status_code == 200
        assert resp.json()["display_name"] == "New Name"
        mock_users_repo.update_profile.assert_called_once_with(
            "test_user", {"name": "New Name", "nameLower": "new name"}
        )

    def test_patch_avatar_alone(self, patch_client, mock_users_repo):
        before = _make_profile()
        after = _make_profile(profile_url="https://cdn.example.com/a.png")
        mock_users_repo.get_private_profile.side_effect = [before, after]

        resp = patch_client.patch(
            "/me/clubhouse/profile",
            json={"avatar_url": "https://cdn.example.com/a.png"},
        )

        assert resp.status_code == 200
        assert resp.json()["avatar_url"] == "https://cdn.example.com/a.png"
        mock_users_repo.update_profile.assert_called_once_with(
            "test_user", {"profileUrl": "https://cdn.example.com/a.png"}
        )

    def test_patch_area_alone(self, patch_client, mock_users_repo):
        mock_users_repo.get_private_profile.side_effect = [
            _make_profile(),
            _make_profile(),
        ]

        resp = patch_client.patch("/me/clubhouse/profile", json={"area": 202})

        assert resp.status_code == 200
        mock_users_repo.update_profile.assert_called_once_with(
            "test_user", {"preferences.area": 202}
        )

    def test_patch_levels_alone(self, patch_client, mock_users_repo):
        mock_users_repo.get_private_profile.side_effect = [
            _make_profile(),
            _make_profile(),
        ]

        resp = patch_client.patch(
            "/me/clubhouse/profile", json={"levels": {"padel": "intermediate"}}
        )

        assert resp.status_code == 200
        mock_users_repo.update_profile.assert_called_once_with(
            "test_user", {"preferences.levels.padel": "intermediate"}
        )

    def test_patch_multiple_fields_combined(self, patch_client, mock_users_repo):
        mock_users_repo.get_private_profile.side_effect = [
            _make_profile(),
            _make_profile(),
        ]

        resp = patch_client.patch(
            "/me/clubhouse/profile",
            json={
                "display_name": "Combo",
                "area": 101,
                "levels": {"tennis": "advanced"},
            },
        )

        assert resp.status_code == 200
        mock_users_repo.update_profile.assert_called_once_with(
            "test_user",
            {
                "name": "Combo",
                "nameLower": "combo",
                "preferences.area": 101,
                "preferences.levels.tennis": "advanced",
            },
        )

    def test_patch_area_and_levels_round_trip_in_response(
        self, patch_client, mock_users_repo
    ):
        before = _make_profile(area=101, levels=PerSportLevels())
        after = _make_profile(
            area=202,
            levels=PerSportLevels(
                tennis=LevelEnum.ADVANCED,
                padel=LevelEnum.BEGINNER,
            ),
        )
        mock_users_repo.get_private_profile.side_effect = [before, after]

        resp = patch_client.patch(
            "/me/clubhouse/profile",
            json={"area": 202, "levels": {"tennis": "advanced", "padel": "beginner"}},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["area"] == 202
        assert data["levels"] == {
            "tennis": "advanced",
            "padel": "beginner",
            "pickleball": None,
        }

    def test_levels_update_emits_no_rankings_paths(self, patch_client, mock_users_repo):
        mock_users_repo.get_private_profile.side_effect = [
            _make_profile(),
            _make_profile(),
        ]

        resp = patch_client.patch(
            "/me/clubhouse/profile",
            json={"levels": {"tennis": "pro", "padel": "beginner"}},
        )

        assert resp.status_code == 200
        _, updates = mock_users_repo.update_profile.call_args[0]
        assert all(not key.startswith("rankings") for key in updates)

    def test_empty_body_returns_400(self, patch_client, mock_users_repo):
        resp = patch_client.patch("/me/clubhouse/profile", json={})
        assert resp.status_code == 400
        mock_users_repo.update_profile.assert_not_called()

    def test_empty_levels_object_returns_400(self, patch_client, mock_users_repo):
        # {"levels": {}} passes the top-level "is anything set" check (levels
        # is not None) but builds zero dot-paths — must not reach Firestore
        # with an empty update dict.
        mock_users_repo.get_private_profile.return_value = _make_profile()

        resp = patch_client.patch("/me/clubhouse/profile", json={"levels": {}})

        assert resp.status_code == 400
        mock_users_repo.update_profile.assert_not_called()

    def test_levels_all_explicit_null_returns_400(self, patch_client, mock_users_repo):
        # Every sport key present but explicitly null: fields_set is non-empty
        # so the per-sport loop runs, but each value is None so no dot-path is
        # emitted — same empty-update hazard as {"levels": {}}.
        mock_users_repo.get_private_profile.return_value = _make_profile()

        resp = patch_client.patch(
            "/me/clubhouse/profile",
            json={"levels": {"tennis": None, "padel": None, "pickleball": None}},
        )

        assert resp.status_code == 400
        mock_users_repo.update_profile.assert_not_called()

    def test_unknown_area_returns_422(self, patch_client, mock_users_repo):
        resp = patch_client.patch("/me/clubhouse/profile", json={"area": 999})
        assert resp.status_code == 422
        mock_users_repo.update_profile.assert_not_called()

    def test_http_avatar_url_returns_422(self, patch_client, mock_users_repo):
        resp = patch_client.patch(
            "/me/clubhouse/profile", json={"avatar_url": "http://cdn.example.com/a.png"}
        )
        assert resp.status_code == 422
        mock_users_repo.update_profile.assert_not_called()

    def test_invalid_level_returns_422(self, patch_client, mock_users_repo):
        resp = patch_client.patch(
            "/me/clubhouse/profile", json={"levels": {"tennis": "expert"}}
        )
        assert resp.status_code == 422
        mock_users_repo.update_profile.assert_not_called()

    def test_unknown_sport_key_returns_422(self, patch_client, mock_users_repo):
        resp = patch_client.patch(
            "/me/clubhouse/profile", json={"levels": {"cricket": "advanced"}}
        )
        assert resp.status_code == 422
        mock_users_repo.update_profile.assert_not_called()

    def test_unknown_top_level_field_returns_422(self, patch_client, mock_users_repo):
        resp = patch_client.patch("/me/clubhouse/profile", json={"nickname": "x"})
        assert resp.status_code == 422
        mock_users_repo.update_profile.assert_not_called()

    def test_empty_display_name_returns_422(self, patch_client, mock_users_repo):
        resp = patch_client.patch("/me/clubhouse/profile", json={"display_name": "   "})
        assert resp.status_code == 422
        mock_users_repo.update_profile.assert_not_called()

    def test_user_not_found_returns_404(self, patch_client, mock_users_repo):
        mock_users_repo.get_private_profile.return_value = None

        resp = patch_client.patch("/me/clubhouse/profile", json={"display_name": "X"})

        assert resp.status_code == 404
        mock_users_repo.update_profile.assert_not_called()

    def test_no_auth_returns_401(self, mock_region_config_repo):
        previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides[get_region_config_repo] = (
            lambda: mock_region_config_repo
        )
        try:
            test_client = TestClient(app)
            resp = test_client.patch(
                "/me/clubhouse/profile", json={"display_name": "X"}
            )
            assert resp.status_code == 401
        finally:
            app.dependency_overrides = previous_overrides
