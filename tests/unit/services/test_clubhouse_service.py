from __future__ import annotations

import pytest

from datetime import datetime, timezone

from app.constants import STREAK_MILESTONES
from app.models.common import SportRanking, UserCompletedMatchSummary
from app.models.enums import MatchResultEnum, SportEnum, TierEnum
from app.services.clubhouse_service import (
    build_athlete_card_sports,
    check_personal_best,
    compute_match_totals,
    is_streak_milestone,
    update_streak_on_loss,
    update_streak_on_win,
)


# ---------------------------------------------------------------------------
# check_personal_best
# ---------------------------------------------------------------------------


class TestCheckPersonalBest:
    def test_first_match_sets_personal_best(self) -> None:
        is_new, value = check_personal_best(500, None)
        assert is_new is True
        assert value == 500

    def test_new_pts_exceeds_current_best(self) -> None:
        is_new, value = check_personal_best(600, 500)
        assert is_new is True
        assert value == 600

    def test_new_pts_equals_current_best(self) -> None:
        is_new, value = check_personal_best(500, 500)
        assert is_new is False
        assert value == 500

    def test_new_pts_below_current_best(self) -> None:
        is_new, value = check_personal_best(400, 500)
        assert is_new is False
        assert value == 500

    def test_loss_decreased_pts_not_personal_best(self) -> None:
        is_new, value = check_personal_best(350, 500)
        assert is_new is False
        assert value == 500

    def test_first_match_zero_pts(self) -> None:
        is_new, value = check_personal_best(0, None)
        assert is_new is True
        assert value == 0

    def test_exceeds_by_one(self) -> None:
        is_new, value = check_personal_best(501, 500)
        assert is_new is True
        assert value == 501


# ---------------------------------------------------------------------------
# update_streak_on_win
# ---------------------------------------------------------------------------


class TestUpdateStreakOnWin:
    def test_first_win_ever(self) -> None:
        new_current, new_best = update_streak_on_win(0, 0)
        assert new_current == 1
        assert new_best == 1

    def test_consecutive_win_below_best(self) -> None:
        new_current, new_best = update_streak_on_win(2, 5)
        assert new_current == 3
        assert new_best == 5

    def test_consecutive_win_equals_best(self) -> None:
        new_current, new_best = update_streak_on_win(4, 5)
        assert new_current == 5
        assert new_best == 5

    def test_consecutive_win_exceeds_best(self) -> None:
        new_current, new_best = update_streak_on_win(5, 5)
        assert new_current == 6
        assert new_best == 6

    def test_win_after_loss_resets_current(self) -> None:
        # After a loss, current_streak is 0; first win brings it to 1
        new_current, new_best = update_streak_on_win(0, 10)
        assert new_current == 1
        assert new_best == 10

    def test_large_streak(self) -> None:
        new_current, new_best = update_streak_on_win(99, 99)
        assert new_current == 100
        assert new_best == 100


# ---------------------------------------------------------------------------
# update_streak_on_loss
# ---------------------------------------------------------------------------


class TestUpdateStreakOnLoss:
    def test_loss_resets_current_streak(self) -> None:
        new_current, new_best = update_streak_on_loss(7, 10)
        assert new_current == 0
        assert new_best == 10

    def test_loss_when_already_zero(self) -> None:
        new_current, new_best = update_streak_on_loss(0, 3)
        assert new_current == 0
        assert new_best == 3

    def test_loss_preserves_best_streak(self) -> None:
        new_current, new_best = update_streak_on_loss(5, 5)
        assert new_current == 0
        assert new_best == 5

    def test_first_match_loss(self) -> None:
        new_current, new_best = update_streak_on_loss(0, 0)
        assert new_current == 0
        assert new_best == 0


# ---------------------------------------------------------------------------
# is_streak_milestone
# ---------------------------------------------------------------------------


class TestIsStreakMilestone:
    @pytest.mark.parametrize("streak", sorted(STREAK_MILESTONES))
    def test_milestone_values(self, streak: int) -> None:
        assert is_streak_milestone(streak) is True

    @pytest.mark.parametrize("streak", [0, 1, 2, 4, 6, 7, 8, 9, 11, 15, 19, 21, 50])
    def test_non_milestone_values(self, streak: int) -> None:
        assert is_streak_milestone(streak) is False

    def test_milestone_set_contains_expected_values(self) -> None:
        assert STREAK_MILESTONES == frozenset({3, 5, 10, 20})


# ---------------------------------------------------------------------------
# Integrated streak sequence
# ---------------------------------------------------------------------------


class TestStreakSequence:
    def test_win_loss_win_sequence(self) -> None:
        """Simulate: W, W, W, L, W, W — verify streak tracking end-to-end."""
        current, best = 0, 0

        # 3 wins
        current, best = update_streak_on_win(current, best)
        assert (current, best) == (1, 1)
        current, best = update_streak_on_win(current, best)
        assert (current, best) == (2, 2)
        current, best = update_streak_on_win(current, best)
        assert (current, best) == (3, 3)
        assert is_streak_milestone(current) is True

        # loss
        current, best = update_streak_on_loss(current, best)
        assert (current, best) == (0, 3)

        # 2 more wins
        current, best = update_streak_on_win(current, best)
        assert (current, best) == (1, 3)
        current, best = update_streak_on_win(current, best)
        assert (current, best) == (2, 3)


# ---------------------------------------------------------------------------
# build_athlete_card_sports
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class TestBuildAthleteCardSports:
    def test_single_sport(self) -> None:
        rankings = {
            "tennis": SportRanking(
                sport=SportEnum.TENNIS,
                pts=820,
                global_ranking=340,
                tier=TierEnum.AMATEUR,
                personal_best=850,
                current_streak=3,
                best_streak=5,
            ),
            "padel": None,
            "pickleball": None,
        }
        result = build_athlete_card_sports(rankings)
        assert len(result) == 1
        assert result[0]["sport"] == SportEnum.TENNIS
        assert result[0]["pts"] == 820
        assert result[0]["tier"] == "amateur"
        assert result[0]["global_ranking"] == 340
        assert result[0]["personal_best"] == 850
        assert result[0]["current_streak"] == 3
        assert result[0]["best_streak"] == 5

    def test_multiple_sports(self) -> None:
        rankings = {
            "tennis": SportRanking(sport=SportEnum.TENNIS, pts=500),
            "padel": SportRanking(
                sport=SportEnum.PADEL, pts=700, tier=TierEnum.INTERMEDIATE
            ),
            "pickleball": None,
        }
        result = build_athlete_card_sports(rankings)
        assert len(result) == 2

    def test_no_rankings(self) -> None:
        rankings = {"tennis": None, "padel": None, "pickleball": None}
        result = build_athlete_card_sports(rankings)
        assert result == []

    def test_tier_defaults_to_amateur(self) -> None:
        rankings = {
            "tennis": SportRanking(sport=SportEnum.TENNIS, pts=100),
            "padel": None,
            "pickleball": None,
        }
        result = build_athlete_card_sports(rankings)
        assert result[0]["tier"] == "amateur"


# ---------------------------------------------------------------------------
# compute_match_totals
# ---------------------------------------------------------------------------


class TestComputeMatchTotals:
    def test_empty_list_returns_zero(self) -> None:
        total, wins = compute_match_totals([])
        assert total == 0
        assert wins == 0

    def test_ignores_capped_cache_returns_zero(self) -> None:
        """completedMatches is capped at 10 items; totals must not use it.

        Until uncapped counter fields are added to the user document,
        compute_match_totals returns (0, 0) as a safe fallback.
        """
        matches = [
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
        ]
        total, wins = compute_match_totals(matches)
        assert total == 0
        assert wins == 0
