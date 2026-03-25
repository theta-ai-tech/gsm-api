"""
Unit tests for GET /me/lab/progression and GET /me/lab/dashboard.

Repos are mocked — no emulator needed.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import (
    get_leaderboard_repo,
    get_matches_repo,
    get_point_history_repo,
    get_region_config_repo,
    get_scouting_repo,
    get_ticker_repo,
    get_tier_config_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.main import app
from app.models.common import (
    PerSportLevels,
    PerSportRankings,
    SportRanking,
    UserCompletedMatchSummary,
    UserPreferences,
)
from app.models.enums import (
    MatchResultEnum,
    PointHistoryReasonEnum,
    SportEnum,
    TierEnum,
)
from app.models.point_history import PointHistoryEntry
from app.models.tier import TierConfig, TierThreshold
from app.models.leaderboard import (
    LeaderboardEntry,
    LeaderboardSnapshot,
    RisingStarEntry,
)
from app.models.region_config import RegionConfig
from app.models.skill_dna import SkillAxisData, SportSkillDna
from app.models.ticker import TickerEvent
from app.models.match import Match
from app.models.common import MatchScore, SetScore
from app.models.user import PrivateUserProfile
from app.models.enums import MatchStatusEnum
from app.routers.lab import (
    _build_axes,
    _compute_quick_stats,
    _encode_cursor,
    _rankings_to_dict,
    _score_text,
)
from app.services.scoring_service import win_probability
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
    tier: TierEnum | None = TierEnum.AMATEUR,
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
        self, skill_dna_client, skill_dna_mock_tier_config_repo
    ) -> None:
        skill_dna_mock_tier_config_repo.get_tier_averages.return_value = {
            "intermediate": {"tennis": {"serve": 75, "power": 70}}
        }
        body = skill_dna_client.get(
            "/me/lab/skill-dna?sport=tennis&compare=next_tier"
        ).json()
        assert body["comparison"]["label"] == "Intermediate Average"
        assert body["comparison"]["axes"]["serve"] == 75

    def test_sport_not_found_returns_404(
        self, skill_dna_mock_users_repo, skill_dna_mock_tier_config_repo
    ) -> None:
        skill_dna_mock_users_repo.get_public_profile.return_value = (
            _make_public_profile(skill_dna={})
        )
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        tier_repo = skill_dna_mock_tier_config_repo
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_users_repo] = lambda: skill_dna_mock_users_repo
            app.dependency_overrides[get_tier_config_repo] = lambda: tier_repo
            resp = TestClient(app).get("/me/lab/skill-dna?sport=padel")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_user_not_found_returns_404(
        self, skill_dna_mock_users_repo, skill_dna_mock_tier_config_repo
    ) -> None:
        skill_dna_mock_users_repo.get_public_profile.return_value = None
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        tier_repo = skill_dna_mock_tier_config_repo
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_users_repo] = lambda: skill_dna_mock_users_repo
            app.dependency_overrides[get_tier_config_repo] = lambda: tier_repo
            resp = TestClient(app).get("/me/lab/skill-dna?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_missing_token_returns_401(self) -> None:
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides = {}
            resp = TestClient(app).get("/me/lab/skill-dna?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, skill_dna_client) -> None:
        resp = skill_dna_client.get("/me/lab/skill-dna?sport=badminton")
        assert resp.status_code == 422

    def test_sport_required(self, skill_dna_client) -> None:
        resp = skill_dna_client.get("/me/lab/skill-dna")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# win_probability (pure unit tests)
# ---------------------------------------------------------------------------


class TestWinProbability:
    def test_equal_pts_returns_half(self) -> None:
        assert win_probability(2000, 2000) == 0.5

    def test_higher_pts_returns_above_half(self) -> None:
        assert win_probability(2500, 2000) > 0.5

    def test_lower_pts_returns_below_half(self) -> None:
        assert win_probability(2000, 2500) < 0.5

    def test_500_advantage_approx_75_pct(self) -> None:
        result = win_probability(2500, 2000)
        assert 0.74 <= result <= 0.76

    def test_symmetry(self) -> None:
        assert win_probability(3000, 2000) + win_probability(
            2000, 3000
        ) == pytest.approx(1.0)

    def test_never_returns_zero(self) -> None:
        assert win_probability(0, 100_000) >= 0.01

    def test_never_returns_one(self) -> None:
        assert win_probability(100_000, 0) <= 0.99

    def test_rounded_to_two_decimals(self) -> None:
        result = win_probability(2100, 2000)
        assert result == round(result, 2)


# ---------------------------------------------------------------------------
# _score_text helper (pure unit tests)
# ---------------------------------------------------------------------------


def _make_match_with_score(sets: list[tuple[int, int]]) -> Match:
    score = MatchScore(
        sets=[SetScore(p1_games=p1, p2_games=p2) for p1, p2 in sets],
        winner_uid="u1",
    )
    return Match(
        match_id="m1",
        sport=SportEnum.TENNIS,
        status=MatchStatusEnum.COMPLETED,
        participant_uids=["u1", "u2"],
        score=score,
    )


class TestScoreText:
    def test_renders_sets(self) -> None:
        m = _make_match_with_score([(6, 4), (3, 6), (7, 5)])
        assert _score_text(m) == "6-4, 3-6, 7-5"

    def test_none_when_no_score(self) -> None:
        m = Match(
            match_id="m1",
            sport=SportEnum.TENNIS,
            status=MatchStatusEnum.COMPLETED,
            participant_uids=["u1", "u2"],
        )
        assert _score_text(m) is None


# ---------------------------------------------------------------------------
# GET /me/lab/rivalry/{opponent_uid} (HTTP)
# ---------------------------------------------------------------------------

_OPP_UID = "user_opponent"


def _make_rivalry_public_profile(
    uid: str, name: str, pts: int, tier: TierEnum
) -> "PublicUserProfile":  # noqa: F821
    from app.models.user import PublicUserProfile

    return PublicUserProfile(
        uid=uid,
        name=name,
        rankings=PerSportRankings(
            tennis=SportRanking(sport=SportEnum.TENNIS, pts=pts, tier=tier),
        ),
    )


@pytest.fixture
def rivalry_users_repo():
    repo = Mock(spec=["get_public_profile"])
    repo.get_public_profile.side_effect = lambda uid: (
        _make_rivalry_public_profile(_UID, "Me", 2000, TierEnum.INTERMEDIATE)
        if uid == _UID
        else _make_rivalry_public_profile(_OPP_UID, "Opponent", 2500, TierEnum.ADVANCED)
    )
    return repo


@pytest.fixture
def rivalry_matches_repo():
    repo = Mock(spec=["list_head_to_head"])
    repo.list_head_to_head.return_value = []
    return repo


@pytest.fixture
def rivalry_client(rivalry_users_repo, rivalry_matches_repo):
    mock_user = CurrentUser(uid=_UID, email="test@example.com")
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_users_repo] = lambda: rivalry_users_repo
    app.dependency_overrides[get_matches_repo] = lambda: rivalry_matches_repo
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


class TestGetRivalry:
    def test_returns_200(self, rivalry_client) -> None:
        resp = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis")
        assert resp.status_code == 200

    def test_response_shape(self, rivalry_client) -> None:
        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        assert body["sport"] == "tennis"
        assert body["me"]["uid"] == _UID
        assert body["opponent"]["uid"] == _OPP_UID
        assert "win_probability" in body
        assert "head_to_head" in body
        assert "recent_matches" in body

    def test_player_pts_and_tier(self, rivalry_client) -> None:
        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        assert body["me"]["pts"] == 2000
        assert body["me"]["tier"] == "intermediate"
        assert body["opponent"]["pts"] == 2500
        assert body["opponent"]["tier"] == "advanced"

    def test_win_probability_lower_when_behind(self, rivalry_client) -> None:
        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        assert body["win_probability"] < 0.5  # me=2000, opp=2500

    def test_empty_h2h_when_no_matches(self, rivalry_client) -> None:
        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        h2h = body["head_to_head"]
        assert h2h["my_wins"] == 0
        assert h2h["opponent_wins"] == 0
        assert h2h["total_matches"] == 0
        assert body["recent_matches"] == []

    def test_h2h_counts_wins_correctly(
        self, rivalry_client, rivalry_matches_repo
    ) -> None:
        def _h2h_match(match_id: str, winner: str) -> Match:
            return Match(
                match_id=match_id,
                sport=SportEnum.TENNIS,
                status=MatchStatusEnum.COMPLETED,
                finished_at=_NOW,
                participant_uids=[_UID, _OPP_UID],
                result_by_user={
                    winner: MatchResultEnum.WIN,
                    (_OPP_UID if winner == _UID else _UID): MatchResultEnum.LOSS,
                },
            )

        rivalry_matches_repo.list_head_to_head.return_value = [
            _h2h_match("m1", _UID),
            _h2h_match("m2", _OPP_UID),
            _h2h_match("m3", _UID),
        ]
        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        assert body["head_to_head"]["my_wins"] == 2
        assert body["head_to_head"]["opponent_wins"] == 1
        assert body["head_to_head"]["total_matches"] == 3

    def test_recent_matches_include_score_text_and_result(
        self, rivalry_client, rivalry_matches_repo
    ) -> None:
        rivalry_matches_repo.list_head_to_head.return_value = [
            Match(
                match_id="m1",
                sport=SportEnum.TENNIS,
                status=MatchStatusEnum.COMPLETED,
                finished_at=_NOW,
                participant_uids=[_UID, _OPP_UID],
                result_by_user={
                    _UID: MatchResultEnum.WIN,
                    _OPP_UID: MatchResultEnum.LOSS,
                },
                score=MatchScore(
                    sets=[
                        SetScore(p1_games=6, p2_games=4),
                        SetScore(p1_games=7, p2_games=5),
                    ],
                    winner_uid=_UID,
                ),
            )
        ]
        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        rm = body["recent_matches"][0]
        assert rm["match_id"] == "m1"
        assert rm["score_text"] == "6-4, 7-5"
        assert rm["result"] == "W"

    def test_skill_dna_comparison_null_when_no_dna(self, rivalry_client) -> None:
        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        assert body["skill_dna_comparison"] is None

    def test_opponent_not_found_returns_404(
        self, rivalry_users_repo, rivalry_matches_repo
    ) -> None:
        rivalry_users_repo.get_public_profile.side_effect = lambda uid: (
            _make_rivalry_public_profile(_UID, "Me", 2000, TierEnum.INTERMEDIATE)
            if uid == _UID
            else None
        )
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        matches_repo = rivalry_matches_repo
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_users_repo] = lambda: rivalry_users_repo
            app.dependency_overrides[get_matches_repo] = lambda: matches_repo
            resp = TestClient(app).get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_missing_token_returns_401(self) -> None:
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides = {}
            resp = TestClient(app).get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, rivalry_client) -> None:
        resp = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=badminton")
        assert resp.status_code == 422

    def test_sport_required(self, rivalry_client) -> None:
        resp = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /me/lab/scouting/{opponent_uid} (HTTP)
# ---------------------------------------------------------------------------

_SCOUTING_UID = "user_scouted"


def _make_scouting_profile(
    uid: str = _SCOUTING_UID,
    sport: str = "tennis",
    weak: dict | None = None,
    strong: dict | None = None,
    total_reports: int = 12,
    unique_reporters: int = 8,
):
    from app.models.scouting import ScoutingProfile, ScoutingSportData, ScoutingTagCount

    weak = weak or {
        "backhand": ScoutingTagCount(count=7, last_reported=_NOW),
        "stamina_set3": ScoutingTagCount(count=3, last_reported=_NOW),
    }
    strong = strong or {
        "first_serve": ScoutingTagCount(count=5, last_reported=_NOW),
    }
    sport_data = ScoutingSportData(
        weak=weak,
        strong=strong,
        total_reports=total_reports,
        unique_reporters=unique_reporters,
        last_updated=_NOW,
    )
    kwargs = {sport: sport_data}
    return ScoutingProfile(uid=uid, **kwargs)


@pytest.fixture
def mock_scouting_repo():
    return Mock(spec=["get_profile"])


@pytest.fixture
def scouting_client(mock_scouting_repo):
    mock_scouting_repo.get_profile.return_value = _make_scouting_profile()
    mock_user = CurrentUser(uid=_UID, email="test@example.com")
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_scouting_repo] = lambda: mock_scouting_repo
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


class TestGetScouting:
    def test_returns_200(self, scouting_client) -> None:
        resp = scouting_client.get(f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis")
        assert resp.status_code == 200

    def test_response_shape(self, scouting_client) -> None:
        body = scouting_client.get(
            f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis"
        ).json()
        assert body["uid"] == _SCOUTING_UID
        assert body["sport"] == "tennis"
        assert body["total_reports"] == 12
        assert body["unique_reporters"] == 8
        assert body["confidence"] == "high"
        assert body["last_updated"] is not None

    def test_weak_tags_sorted_descending(self, scouting_client) -> None:
        body = scouting_client.get(
            f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis"
        ).json()
        weak = body["weak"]
        assert len(weak) == 2
        assert weak[0]["tag"] == "backhand"
        assert weak[0]["count"] == 7
        assert weak[0]["label"] == "Backhand"
        assert weak[1]["tag"] == "stamina_set3"
        assert weak[1]["count"] == 3
        assert weak[1]["label"] == "Late-set stamina"

    def test_strong_tags_present(self, scouting_client) -> None:
        body = scouting_client.get(
            f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis"
        ).json()
        strong = body["strong"]
        assert len(strong) == 1
        assert strong[0]["tag"] == "first_serve"
        assert strong[0]["count"] == 5
        assert strong[0]["label"] == "First serve"

    def test_confidence_low(self, scouting_client, mock_scouting_repo) -> None:
        mock_scouting_repo.get_profile.return_value = _make_scouting_profile(
            total_reports=2
        )
        body = scouting_client.get(
            f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis"
        ).json()
        assert body["confidence"] == "low"

    def test_confidence_medium(self, scouting_client, mock_scouting_repo) -> None:
        mock_scouting_repo.get_profile.return_value = _make_scouting_profile(
            total_reports=5
        )
        body = scouting_client.get(
            f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis"
        ).json()
        assert body["confidence"] == "medium"

    def test_no_profile_returns_404(self, mock_scouting_repo) -> None:
        mock_scouting_repo.get_profile.return_value = None
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_scouting_repo] = lambda: mock_scouting_repo
            resp = TestClient(app).get(f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_no_sport_data_returns_404(self, mock_scouting_repo) -> None:
        from app.models.scouting import ScoutingProfile

        mock_scouting_repo.get_profile.return_value = ScoutingProfile(uid=_SCOUTING_UID)
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_scouting_repo] = lambda: mock_scouting_repo
            resp = TestClient(app).get(f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_empty_sport_data_returns_404(self, mock_scouting_repo) -> None:
        profile = _make_scouting_profile(
            weak={}, strong={}, total_reports=0, unique_reporters=0
        )
        mock_scouting_repo.get_profile.return_value = profile
        mock_user = CurrentUser(uid=_UID, email="test@example.com")
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_scouting_repo] = lambda: mock_scouting_repo
            resp = TestClient(app).get(f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 404

    def test_missing_token_returns_401(self) -> None:
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides = {}
            resp = TestClient(app).get(f"/me/lab/scouting/{_SCOUTING_UID}?sport=tennis")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, scouting_client) -> None:
        resp = scouting_client.get(f"/me/lab/scouting/{_SCOUTING_UID}?sport=badminton")
        assert resp.status_code == 422

    def test_sport_required(self, scouting_client) -> None:
        resp = scouting_client.get(f"/me/lab/scouting/{_SCOUTING_UID}")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Leaderboard endpoint
# ---------------------------------------------------------------------------

_LB_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _make_snapshot(
    region: str = "athens", sport: SportEnum = SportEnum.TENNIS
) -> LeaderboardSnapshot:
    return LeaderboardSnapshot(
        region=region,
        sport=sport,
        entries=[
            LeaderboardEntry(
                uid="user_123",
                name="Alex",
                pts=3450,
                tier=TierEnum.ADVANCED,
                rank=1,
                delta7d=250,
            ),
            LeaderboardEntry(
                uid="user_456",
                name="Ben",
                pts=3100,
                tier=TierEnum.ADVANCED,
                rank=2,
                delta7d=-50,
            ),
        ],
        rising_stars=[
            RisingStarEntry(
                uid="user_789", name="Dana", pts=2100, delta7d=400, rank=15
            ),
        ],
        last_updated=_LB_NOW,
    )


def _make_region_config() -> RegionConfig:
    return RegionConfig(
        mapping={"101": "athens", "202": "thessaloniki", "303": "london"},
        version=1,
    )


def _make_private_profile_for_lb(area: int = 101) -> PrivateUserProfile:
    return PrivateUserProfile(
        uid=_UID,
        name="Test User",
        email="test@example.com",
        rankings=PerSportRankings(),
        preferences=UserPreferences(
            area=area,
            levels=PerSportLevels(),
            sports=[],
        ),
    )


@pytest.fixture
def leaderboard_client():
    mock_lb_repo = Mock(spec=["get_snapshot"])
    mock_users = Mock(spec=["get_private_profile"])
    mock_region = Mock(spec=["get"])
    mock_user = CurrentUser(uid=_UID, email="test@example.com")

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_leaderboard_repo] = lambda: mock_lb_repo
    app.dependency_overrides[get_users_repo] = lambda: mock_users
    app.dependency_overrides[get_region_config_repo] = lambda: mock_region
    yield TestClient(app), mock_lb_repo, mock_users, mock_region
    app.dependency_overrides = previous_overrides


class TestGetLeaderboard:
    def test_returns_200_with_explicit_region(self, leaderboard_client):
        client, mock_lb, _, _ = leaderboard_client
        mock_lb.get_snapshot.return_value = _make_snapshot()

        resp = client.get("/me/lab/leaderboard?sport=tennis&region=athens")

        assert resp.status_code == 200
        body = resp.json()
        assert body["region"] == "athens"
        assert body["sport"] == "tennis"
        assert len(body["entries"]) == 2
        assert len(body["rising_stars"]) == 1
        assert body["last_updated"] is not None

    def test_entry_fields(self, leaderboard_client):
        client, mock_lb, _, _ = leaderboard_client
        mock_lb.get_snapshot.return_value = _make_snapshot()

        body = client.get("/me/lab/leaderboard?sport=tennis&region=athens").json()

        entry = body["entries"][0]
        assert entry["uid"] == "user_123"
        assert entry["name"] == "Alex"
        assert entry["pts"] == 3450
        assert entry["tier"] == "advanced"
        assert entry["rank"] == 1
        assert entry["delta7d"] == 250

    def test_rising_star_fields(self, leaderboard_client):
        client, mock_lb, _, _ = leaderboard_client
        mock_lb.get_snapshot.return_value = _make_snapshot()

        body = client.get("/me/lab/leaderboard?sport=tennis&region=athens").json()

        star = body["rising_stars"][0]
        assert star["uid"] == "user_789"
        assert star["name"] == "Dana"
        assert star["pts"] == 2100
        assert star["delta7d"] == 400
        assert star["rank"] == 15

    def test_defaults_region_from_user_preferences(self, leaderboard_client):
        client, mock_lb, mock_users, mock_region = leaderboard_client
        mock_users.get_private_profile.return_value = _make_private_profile_for_lb(
            area=101
        )
        mock_region.get.return_value = _make_region_config()
        mock_lb.get_snapshot.return_value = _make_snapshot()

        resp = client.get("/me/lab/leaderboard?sport=tennis")

        assert resp.status_code == 200
        mock_lb.get_snapshot.assert_called_once_with("athens", "tennis")

    def test_explicit_region_skips_user_lookup(self, leaderboard_client):
        client, mock_lb, mock_users, mock_region = leaderboard_client
        mock_lb.get_snapshot.return_value = _make_snapshot(region="london")

        resp = client.get("/me/lab/leaderboard?sport=tennis&region=london")

        assert resp.status_code == 200
        mock_users.get_private_profile.assert_not_called()
        mock_region.get.assert_not_called()

    def test_404_when_no_leaderboard_for_region_sport(self, leaderboard_client):
        client, mock_lb, _, _ = leaderboard_client
        mock_lb.get_snapshot.return_value = None

        resp = client.get("/me/lab/leaderboard?sport=tennis&region=narnia")

        assert resp.status_code == 404

    def test_404_when_user_profile_not_found_for_default_region(
        self, leaderboard_client
    ):
        client, mock_lb, mock_users, mock_region = leaderboard_client
        mock_users.get_private_profile.return_value = None

        resp = client.get("/me/lab/leaderboard?sport=tennis")

        assert resp.status_code == 404

    def test_404_when_area_not_in_region_mapping(self, leaderboard_client):
        client, mock_lb, mock_users, mock_region = leaderboard_client
        mock_users.get_private_profile.return_value = _make_private_profile_for_lb(
            area=999
        )
        mock_region.get.return_value = _make_region_config()

        resp = client.get("/me/lab/leaderboard?sport=tennis")

        assert resp.status_code == 404

    def test_invalid_sport_returns_422(self, leaderboard_client):
        client, _, _, _ = leaderboard_client

        resp = client.get("/me/lab/leaderboard?sport=badminton&region=athens")

        assert resp.status_code == 422

    def test_sport_required_returns_422(self, leaderboard_client):
        client, _, _, _ = leaderboard_client

        resp = client.get("/me/lab/leaderboard?region=athens")

        assert resp.status_code == 422

    def test_missing_token_returns_401(self):
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides = {}
            resp = TestClient(app).get("/me/lab/leaderboard?sport=tennis&region=athens")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Ticker endpoint
# ---------------------------------------------------------------------------


def _make_ticker_event(
    event_id: str = "evt_1",
    event_type: str = "upset",
    sport: str = "tennis",
    region: str = "athens",
) -> TickerEvent:
    kwargs: dict[str, Any] = {
        "event_id": event_id,
        "type": event_type,
        "sport": sport,
        "region": region,
        "created_at": _NOW,
        "expires_at": _NOW,
    }
    if event_type == "upset":
        kwargs.update(
            winner_uid="u1",
            winner_name="Dana",
            loser_tier=TierEnum.ADVANCED,
            delta=200,
        )
    elif event_type == "win_streak":
        kwargs.update(user_uid="u2", user_name="Alex", streak=5)
    elif event_type == "personal_best":
        kwargs.update(user_uid="u3", user_name="Ben", new_pts=1500, previous_best=1200)
    return TickerEvent(**kwargs)


@pytest.fixture
def ticker_client():
    mock_ticker_repo = Mock(spec=["list_by_region_sport"])
    mock_users = Mock(spec=["get_private_profile"])
    mock_region = Mock(spec=["get"])
    mock_user = CurrentUser(uid=_UID, email="test@example.com")

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_ticker_repo] = lambda: mock_ticker_repo
    app.dependency_overrides[get_users_repo] = lambda: mock_users
    app.dependency_overrides[get_region_config_repo] = lambda: mock_region
    yield TestClient(app), mock_ticker_repo, mock_users, mock_region
    app.dependency_overrides = previous_overrides


class TestGetTicker:
    def test_returns_200_with_explicit_region(self, ticker_client):
        client, mock_ticker, _, _ = ticker_client
        mock_ticker.list_by_region_sport.return_value = [_make_ticker_event()]

        resp = client.get("/me/lab/ticker?sport=tennis&region=athens")

        assert resp.status_code == 200
        body = resp.json()
        assert body["region"] == "athens"
        assert body["sport"] == "tennis"
        assert len(body["events"]) == 1

    def test_event_fields_shape(self, ticker_client):
        client, mock_ticker, _, _ = ticker_client
        mock_ticker.list_by_region_sport.return_value = [_make_ticker_event()]

        body = client.get("/me/lab/ticker?sport=tennis&region=athens").json()

        event = body["events"][0]
        assert event["type"] == "upset"
        assert event["sport"] == "tennis"
        assert event["winner_name"] == "Dana"
        assert event["loser_tier"] == "advanced"
        assert event["delta"] == 200
        assert "created_at" in event
        assert "expires_at" in event

    def test_repo_called_with_correct_args(self, ticker_client):
        client, mock_ticker, _, _ = ticker_client
        mock_ticker.list_by_region_sport.return_value = []

        client.get("/me/lab/ticker?sport=tennis&region=athens&limit=10")

        mock_ticker.list_by_region_sport.assert_called_once_with(
            region="athens",
            sport="tennis",
            limit=10,
        )

    def test_default_limit_applied(self, ticker_client):
        client, mock_ticker, _, _ = ticker_client
        mock_ticker.list_by_region_sport.return_value = []

        client.get("/me/lab/ticker?sport=tennis&region=athens")

        mock_ticker.list_by_region_sport.assert_called_once_with(
            region="athens",
            sport="tennis",
            limit=20,
        )

    def test_defaults_region_from_user_preferences(self, ticker_client):
        client, mock_ticker, mock_users, mock_region = ticker_client
        mock_ticker.list_by_region_sport.return_value = []
        mock_users.get_private_profile.return_value = _make_private_profile_for_lb()
        mock_region.get.return_value = _make_region_config()

        resp = client.get("/me/lab/ticker?sport=tennis")

        assert resp.status_code == 200
        assert resp.json()["region"] == "athens"

    def test_empty_events_returns_200(self, ticker_client):
        client, mock_ticker, _, _ = ticker_client
        mock_ticker.list_by_region_sport.return_value = []

        resp = client.get("/me/lab/ticker?sport=tennis&region=athens")

        assert resp.status_code == 200
        assert resp.json()["events"] == []

    def test_limit_over_max_returns_422(self, ticker_client):
        client, _, _, _ = ticker_client

        resp = client.get("/me/lab/ticker?sport=tennis&region=athens&limit=100")

        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, ticker_client):
        client, _, _, _ = ticker_client

        resp = client.get("/me/lab/ticker?sport=tennis&region=athens&limit=0")

        assert resp.status_code == 422

    def test_invalid_sport_returns_422(self, ticker_client):
        client, _, _, _ = ticker_client

        resp = client.get("/me/lab/ticker?sport=badminton&region=athens")

        assert resp.status_code == 422

    def test_sport_required_returns_422(self, ticker_client):
        client, _, _, _ = ticker_client

        resp = client.get("/me/lab/ticker?region=athens")

        assert resp.status_code == 422

    def test_missing_token_returns_401(self):
        previous_overrides = dict(app.dependency_overrides)
        try:
            app.dependency_overrides = {}
            resp = TestClient(app).get("/me/lab/ticker?sport=tennis&region=athens")
        finally:
            app.dependency_overrides = previous_overrides
        assert resp.status_code == 401

    def test_user_not_found_for_default_region_returns_404(self, ticker_client):
        client, _, mock_users, _ = ticker_client
        mock_users.get_private_profile.return_value = None

        resp = client.get("/me/lab/ticker?sport=tennis")

        assert resp.status_code == 404
