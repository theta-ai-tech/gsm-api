"""
Unit tests for GET /me/lab/progression and GET /me/lab/dashboard.

Repos are mocked — no emulator needed.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import (
    get_point_history_repo,
    get_tier_config_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.main import app
from app.models.common import PerSportRankings, SportRanking, UserCompletedMatchSummary
from app.models.enums import (
    MatchResultEnum,
    PointHistoryReasonEnum,
    SportEnum,
    TierEnum,
)
from app.models.point_history import PointHistoryEntry
from app.models.tier import TierConfig, TierThreshold
from app.models.skill_dna import SkillAxisData, SportSkillDna
from app.routers.lab import (
    _build_axes,
    _compute_quick_stats,
    _encode_cursor,
    _rankings_to_dict,
)
from app.security import CurrentUser

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
_UID = "user_test"


def _make_entry(entry_id: str, pts: int = 2000, delta: int = 100) -> PointHistoryEntry:
    return PointHistoryEntry(
        entry_id=entry_id,
        sport=SportEnum.TENNIS,
        pts=pts,
        delta=delta,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match_001",
        opponent_uid="opp_001",
        created_at=_NOW,
        tier_after=TierEnum.INTERMEDIATE,
    )


def _decode_cursor_str(cursor: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(cursor.encode()))


@pytest.fixture
def mock_repo():
    return Mock(spec=["list_entries"])


@pytest.fixture
def mock_user():
    return CurrentUser(uid=_UID, email="test@example.com")


@pytest.fixture
def client(mock_repo, mock_user):
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_point_history_repo] = lambda: mock_repo
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_missing_token_returns_401(self):
        """No dependency override — real auth guard should reject the request."""
        c = TestClient(app)
        resp = c.get("/me/lab/progression?sport=tennis")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestGetProgression:
    def test_returns_entries_for_sport(self, client, mock_repo):
        entries = [_make_entry("e1"), _make_entry("e2")]
        mock_repo.list_entries.return_value = entries

        resp = client.get("/me/lab/progression?sport=tennis")

        assert resp.status_code == 200
        body = resp.json()
        assert body["sport"] == "tennis"
        assert len(body["entries"]) == 2
        assert body["has_more"] is False
        assert body["cursor"] is None

    def test_repo_called_with_correct_args(self, client, mock_repo):
        mock_repo.list_entries.return_value = []

        client.get("/me/lab/progression?sport=padel&limit=10")

        mock_repo.list_entries.assert_called_once_with(
            uid=_UID,
            sport=SportEnum.PADEL,
            limit=11,  # limit+1 for has_more detection
            cursor=None,
        )

    def test_has_more_true_when_extra_entry_returned(self, client, mock_repo):
        # Return limit+1 entries to signal there are more pages.
        entries = [_make_entry(f"e{i}") for i in range(6)]
        mock_repo.list_entries.return_value = entries  # 6 returned for limit=5

        resp = client.get("/me/lab/progression?sport=tennis&limit=5")

        body = resp.json()
        assert body["has_more"] is True
        assert len(body["entries"]) == 5  # extra entry trimmed
        assert body["cursor"] is not None

    def test_cursor_encodes_last_returned_entry(self, client, mock_repo):
        entries = [_make_entry(f"e{i}") for i in range(6)]
        mock_repo.list_entries.return_value = entries

        resp = client.get("/me/lab/progression?sport=tennis&limit=5")

        cursor_data = _decode_cursor_str(resp.json()["cursor"])
        assert cursor_data["entryId"] == "e4"  # index 4 = last of the 5 returned

    def test_cursor_passed_to_repo(self, client, mock_repo):
        entry = _make_entry("e1")
        cursor_str = _encode_cursor(entry)
        mock_repo.list_entries.return_value = []

        client.get(f"/me/lab/progression?sport=tennis&cursor={cursor_str}")

        _, kwargs = mock_repo.list_entries.call_args
        cursor_arg = kwargs["cursor"]
        assert cursor_arg["entryId"] == "e1"
        assert isinstance(cursor_arg["createdAt"], datetime)

    def test_empty_result(self, client, mock_repo):
        mock_repo.list_entries.return_value = []

        resp = client.get("/me/lab/progression?sport=tennis")

        body = resp.json()
        assert body["entries"] == []
        assert body["has_more"] is False
        assert body["cursor"] is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_sport_returns_422(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=badminton")
        assert resp.status_code == 422

    def test_sport_is_required(self, client, mock_repo):
        resp = client.get("/me/lab/progression")
        assert resp.status_code == 422

    def test_limit_above_max_returns_422(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=tennis&limit=201")
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=tennis&limit=0")
        assert resp.status_code == 422

    def test_invalid_cursor_returns_400(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=tennis&cursor=notvalidbase64!!!")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Dashboard helpers (pure unit tests — no HTTP)
# ---------------------------------------------------------------------------

_T1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc)


def _make_match(
    sport: SportEnum,
    result: MatchResultEnum,
    finished_at: datetime = _T1,
) -> UserCompletedMatchSummary:
    return UserCompletedMatchSummary(
        match_id="m1",
        sport=sport,
        finished_at=finished_at,
        result=result,
    )


def _make_tier_config() -> TierConfig:
    return TierConfig(
        thresholds=[
            TierThreshold(
                tier=TierEnum.AMATEUR,
                minPts=0,
                maxPts=999,
                label="Amateur",
                color="#aaa",
            ),
            TierThreshold(
                tier=TierEnum.INTERMEDIATE,
                minPts=1000,
                maxPts=1999,
                label="Intermediate",
                color="#bbb",
            ),
        ],
        version=1,
        updatedAt=_T1,
    )


class TestRankingsToDict:
    def test_returns_only_non_none_sports(self):
        rankings = PerSportRankings(
            tennis=SportRanking(
                sport=SportEnum.TENNIS, pts=2000, tier=TierEnum.INTERMEDIATE
            ),
            padel=None,
        )
        result = _rankings_to_dict(rankings)
        assert set(result.keys()) == {"tennis"}
        assert result["tennis"].pts == 2000

    def test_empty_rankings_returns_empty_dict(self):
        assert _rankings_to_dict(PerSportRankings()) == {}

    def test_all_sports_present(self):
        rankings = PerSportRankings(
            tennis=SportRanking(sport=SportEnum.TENNIS, pts=1000),
            padel=SportRanking(sport=SportEnum.PADEL, pts=500),
            pickleball=SportRanking(sport=SportEnum.PICKLEBALL, pts=200),
        )
        result = _rankings_to_dict(rankings)
        assert set(result.keys()) == {"tennis", "padel", "pickleball"}


class TestComputeQuickStats:
    def test_basic_win_loss_counts(self):
        matches = [
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T1),
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T2),
            _make_match(SportEnum.TENNIS, MatchResultEnum.LOSS, _T3),
        ]
        result = _compute_quick_stats(matches)
        assert result["tennis"].total_matches == 3
        assert result["tennis"].wins == 2
        assert result["tennis"].losses == 1

    def test_win_rate_calculation(self):
        matches = [
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T1),
            _make_match(SportEnum.TENNIS, MatchResultEnum.LOSS, _T2),
        ]
        result = _compute_quick_stats(matches)
        assert result["tennis"].win_rate == 0.5

    def test_win_streak(self):
        matches = [
            _make_match(SportEnum.TENNIS, MatchResultEnum.LOSS, _T1),
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T2),
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T3),
        ]
        result = _compute_quick_stats(matches)
        assert result["tennis"].current_streak == 2
        assert result["tennis"].streak_type == "win"

    def test_loss_streak(self):
        matches = [
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T1),
            _make_match(SportEnum.TENNIS, MatchResultEnum.LOSS, _T2),
            _make_match(SportEnum.TENNIS, MatchResultEnum.LOSS, _T3),
        ]
        result = _compute_quick_stats(matches)
        assert result["tennis"].current_streak == 2
        assert result["tennis"].streak_type == "loss"

    def test_per_sport_isolation(self):
        matches = [
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T1),
            _make_match(SportEnum.PADEL, MatchResultEnum.LOSS, _T1),
        ]
        result = _compute_quick_stats(matches)
        assert "tennis" in result
        assert "padel" in result
        assert result["tennis"].wins == 1
        assert result["padel"].losses == 1

    def test_empty_matches_returns_empty_dict(self):
        assert _compute_quick_stats([]) == {}


# ---------------------------------------------------------------------------
# Dashboard endpoint (HTTP)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_repo():
    return Mock(spec=["get_private_profile"])


@pytest.fixture
def mock_tier_config_repo():
    repo = Mock(spec=["get"])
    repo.get.return_value = _make_tier_config()
    return repo


@pytest.fixture
def dashboard_client(mock_users_repo, mock_tier_config_repo):
    from app.models.common import PerSportLevels, UserPreferences
    from app.models.user import PrivateUserProfile

    mock_users_repo.get_private_profile.return_value = PrivateUserProfile(
        uid=_UID,
        name="Test User",
        email="test@example.com",
        rankings=PerSportRankings(
            tennis=SportRanking(
                sport=SportEnum.TENNIS, pts=2300, tier=TierEnum.INTERMEDIATE
            ),
        ),
        preferences=UserPreferences(
            area=1, levels=PerSportLevels(), sports=[SportEnum.TENNIS]
        ),
        completed_matches=[
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T2),
            _make_match(SportEnum.TENNIS, MatchResultEnum.WIN, _T3),
        ],
        leagues_active=[],
        leagues_completed=[],
        upcoming_matches=[],
        journal_recent=[],
        cursors=None,
    )
    previous_overrides = dict(app.dependency_overrides)
    mock_user = CurrentUser(uid=_UID, email="test@example.com")
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_users_repo] = lambda: mock_users_repo
    app.dependency_overrides[get_tier_config_repo] = lambda: mock_tier_config_repo
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


class TestGetDashboard:
    def test_returns_200(self, dashboard_client):
        resp = dashboard_client.get("/me/lab/dashboard")
        assert resp.status_code == 200

    def test_rankings_contains_sports_with_data(self, dashboard_client):
        body = dashboard_client.get("/me/lab/dashboard").json()
        assert "tennis" in body["rankings"]
        assert "padel" not in body["rankings"]

    def test_ranking_fields(self, dashboard_client):
        body = dashboard_client.get("/me/lab/dashboard").json()
        tennis = body["rankings"]["tennis"]
        assert tennis["pts"] == 2300
        assert tennis["tier"] == "intermediate"

    def test_quick_stats_present(self, dashboard_client):
        body = dashboard_client.get("/me/lab/dashboard").json()
        qs = body["quick_stats"]["tennis"]
        assert qs["total_matches"] == 2
        assert qs["wins"] == 2
        assert qs["streak_type"] == "win"
        assert qs["current_streak"] == 2

    def test_tier_thresholds_present(self, dashboard_client):
        body = dashboard_client.get("/me/lab/dashboard").json()
        assert len(body["tier_thresholds"]) == 2
        tiers = {t["tier"] for t in body["tier_thresholds"]}
        assert tiers == {"amateur", "intermediate"}

    def test_missing_token_returns_401(self):
        c = TestClient(app)
        resp = c.get("/me/lab/dashboard")
        assert resp.status_code == 401

    def test_user_not_found_returns_404(self, mock_users_repo, mock_tier_config_repo):
        mock_users_repo.get_private_profile.return_value = None
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_users_repo] = lambda: mock_users_repo
        app.dependency_overrides[get_tier_config_repo] = lambda: mock_tier_config_repo
        c = TestClient(app)
        resp = c.get("/me/lab/dashboard")
        app.dependency_overrides = previous_overrides
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Skill DNA helpers (pure unit tests)
# ---------------------------------------------------------------------------


def _make_sport_skill_dna(
    serve_pos: int = 0,
    serve_neg: int = 0,
    power_pos: int = 0,
    power_neg: int = 0,
    total: int = 0,
) -> SportSkillDna:
    def _axis(p: int, n: int) -> SkillAxisData | None:
        if p == 0 and n == 0:
            return None
        total_pts = p + n
        score = round(p / total_pts * 100) if total_pts >= 3 else 0
        return SkillAxisData(positive=p, negative=n, score=score)

    return SportSkillDna(
        serve=_axis(serve_pos, serve_neg),
        power=_axis(power_pos, power_neg),
        totalReflections=total,
    )


class TestBuildAxes:
    def test_returns_only_axes_with_data(self) -> None:
        dna = _make_sport_skill_dna(serve_pos=5, serve_neg=2, total=1)
        axes, _ = _build_axes(dna)
        assert "serve" in axes
        assert "power" not in axes

    def test_insufficient_axis_flagged(self) -> None:
        dna = _make_sport_skill_dna(serve_pos=1, serve_neg=1, total=1)
        _, insufficient = _build_axes(dna)
        assert "serve" in insufficient

    def test_sufficient_axis_not_flagged(self) -> None:
        dna = _make_sport_skill_dna(serve_pos=2, serve_neg=1, total=1)
        _, insufficient = _build_axes(dna)
        assert "serve" not in insufficient

    def test_axis_fields_present(self) -> None:
        dna = _make_sport_skill_dna(serve_pos=5, serve_neg=2, total=1)
        axes, _ = _build_axes(dna)
        assert axes["serve"].positive == 5
        assert axes["serve"].negative == 2


# ---------------------------------------------------------------------------
# GET /me/lab/skill-dna (HTTP)
# ---------------------------------------------------------------------------


def _make_public_profile(
    skill_dna: dict | None = None,
    tier: TierEnum | None = TierEnum.INTERMEDIATE,
):
    from app.models.user import PublicUserProfile

    return PublicUserProfile(
        uid=_UID,
        name="Test User",
        rankings=PerSportRankings(
            tennis=SportRanking(sport=SportEnum.TENNIS, pts=2300, tier=tier),
        ),
        skill_dna=skill_dna,
    )


@pytest.fixture
def skill_dna_mock_users_repo():
    return Mock(spec=["get_public_profile"])


@pytest.fixture
def skill_dna_mock_tier_config_repo():
    repo = Mock(spec=["get", "get_tier_averages"])
    repo.get.return_value = _make_tier_config()
    repo.get_tier_averages.return_value = None
    return repo


@pytest.fixture
def skill_dna_client(skill_dna_mock_users_repo, skill_dna_mock_tier_config_repo):
    dna = SportSkillDna(
        serve=SkillAxisData(positive=12, negative=3, score=80),
        power=SkillAxisData(positive=8, negative=5, score=62),
        net_play=SkillAxisData(positive=1, negative=1, score=0),
        totalReflections=23,
    )
    skill_dna_mock_users_repo.get_public_profile.return_value = _make_public_profile(
        skill_dna={"tennis": dna}
    )
    mock_user = CurrentUser(uid=_UID, email="test@example.com")
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_users_repo] = lambda: skill_dna_mock_users_repo
    app.dependency_overrides[get_tier_config_repo] = (
        lambda: skill_dna_mock_tier_config_repo
    )
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


class TestGetSkillDna:
    def test_returns_200(self, skill_dna_client) -> None:
        resp = skill_dna_client.get("/me/lab/skill-dna?sport=tennis")
        assert resp.status_code == 200

    def test_axes_and_total_reflections(self, skill_dna_client) -> None:
        body = skill_dna_client.get("/me/lab/skill-dna?sport=tennis").json()
        assert body["sport"] == "tennis"
        assert body["total_reflections"] == 23
        assert body["axes"]["serve"]["positive"] == 12
        assert body["axes"]["serve"]["score"] == 80
        assert "power" in body["axes"]

    def test_insufficient_axes_flagged(self, skill_dna_client) -> None:
        body = skill_dna_client.get("/me/lab/skill-dna?sport=tennis").json()
        assert "net_play" in body["insufficient_axes"]
        assert "serve" not in body["insufficient_axes"]

    def test_comparison_null_when_tier_averages_missing(self, skill_dna_client) -> None:
        body = skill_dna_client.get(
            "/me/lab/skill-dna?sport=tennis&compare=next_tier"
        ).json()
        assert body["comparison"] is None

    def test_comparison_with_tier_averages(
        self, skill_dna_mock_users_repo, skill_dna_mock_tier_config_repo
    ) -> None:
        skill_dna_mock_tier_config_repo.get_tier_averages.return_value = {
            "intermediate": {"tennis": {"serve": 75, "power": 70}}
        }
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_users_repo] = lambda: skill_dna_mock_users_repo
        app.dependency_overrides[get_tier_config_repo] = (
            lambda: skill_dna_mock_tier_config_repo
        )
        c = TestClient(app)
        body = c.get("/me/lab/skill-dna?sport=tennis&compare=next_tier").json()
        app.dependency_overrides = previous_overrides
        assert body["comparison"]["label"] == "Intermediate Average"
        assert body["comparison"]["axes"]["serve"] == 75

    def test_sport_not_found_returns_404(
        self, skill_dna_mock_users_repo, skill_dna_mock_tier_config_repo
    ) -> None:
        skill_dna_mock_users_repo.get_public_profile.return_value = (
            _make_public_profile(skill_dna={})
        )
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_users_repo] = lambda: skill_dna_mock_users_repo
        app.dependency_overrides[get_tier_config_repo] = (
            lambda: skill_dna_mock_tier_config_repo
        )
        c = TestClient(app)
        resp = c.get("/me/lab/skill-dna?sport=padel")
        app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_user_not_found_returns_404(
        self, skill_dna_mock_users_repo, skill_dna_mock_tier_config_repo
    ) -> None:
        skill_dna_mock_users_repo.get_public_profile.return_value = None
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_users_repo] = lambda: skill_dna_mock_users_repo
        app.dependency_overrides[get_tier_config_repo] = (
            lambda: skill_dna_mock_tier_config_repo
        )
        c = TestClient(app)
        resp = c.get("/me/lab/skill-dna?sport=tennis")
        app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_missing_token_returns_401(self) -> None:
        c = TestClient(app)
        resp = c.get("/me/lab/skill-dna?sport=tennis")
        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, skill_dna_client) -> None:
        resp = skill_dna_client.get("/me/lab/skill-dna?sport=badminton")
        assert resp.status_code == 422

    def test_sport_required(self, skill_dna_client) -> None:
        resp = skill_dna_client.get("/me/lab/skill-dna")
        assert resp.status_code == 422
