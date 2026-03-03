from datetime import datetime, timezone

from app.models.enums import TierEnum
from app.models.tier import TierConfig, TierThreshold
from app.services.scoring_service import (
    ScoreDelta,
    apply_floor,
    calculate_penalty,
    calculate_score_delta,
    compute_match_scoring,
)


def _tier_config() -> TierConfig:
    return TierConfig(
        thresholds=[
            TierThreshold(
                tier=TierEnum.AMATEUR,
                min_pts=1000,
                max_pts=1999,
                label="Amateur",
                color="#8B8B8B",
            ),
            TierThreshold(
                tier=TierEnum.INTERMEDIATE,
                min_pts=2000,
                max_pts=2999,
                label="Intermediate",
                color="#00A3CC",
            ),
            TierThreshold(
                tier=TierEnum.ADVANCED,
                min_pts=3000,
                max_pts=3999,
                label="Advanced",
                color="#BFFF00",
            ),
            TierThreshold(
                tier=TierEnum.COMPETITIVE,
                min_pts=4000,
                max_pts=None,
                label="Competitive",
                color="#FF6B35",
            ),
        ],
        version=1,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class TestCalculateScoreDelta:
    def test_same_tier_match_awards_base_points_only(self) -> None:
        assert calculate_score_delta(
            2100, 2050, TierEnum.INTERMEDIATE, TierEnum.INTERMEDIATE
        ) == (ScoreDelta(total=100, base=100))

    def test_upset_adds_bonus_and_elo_component(self) -> None:
        assert calculate_score_delta(
            2400, 3000, TierEnum.INTERMEDIATE, TierEnum.ADVANCED
        ) == (ScoreDelta(total=180, base=100, upset_bonus=50, elo_bonus=30))


class TestCalculatePenalty:
    def test_loser_penalty_applies_when_losing_to_lower_tier(self) -> None:
        assert (
            calculate_penalty(2200, 1900, TierEnum.INTERMEDIATE, TierEnum.AMATEUR)
            == -50
        )

    def test_no_penalty_when_losing_to_same_or_higher_tier(self) -> None:
        assert (
            calculate_penalty(2200, 2400, TierEnum.INTERMEDIATE, TierEnum.INTERMEDIATE)
            == 0
        )


class TestApplyFloor:
    def test_floor_uses_registration_tier_threshold(self) -> None:
        assert apply_floor(1950, TierEnum.INTERMEDIATE, _tier_config()) == 2000


class TestComputeMatchScoring:
    def test_same_tier_match_keeps_loser_flat(self) -> None:
        result = compute_match_scoring(
            winner_pts=2100,
            loser_pts=2050,
            winner_tier=TierEnum.INTERMEDIATE,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.INTERMEDIATE,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
        )

        assert result.winner_delta == ScoreDelta(total=100, base=100)
        assert result.loser_delta == ScoreDelta(total=0)
        assert result.winner_new_pts == 2200
        assert result.loser_new_pts == 2050
        assert result.winner_new_tier == TierEnum.INTERMEDIATE
        assert result.loser_new_tier == TierEnum.INTERMEDIATE
        assert result.winner_tier_crossed is False
        assert result.loser_tier_crossed is False

    def test_upset_can_cross_tier_and_penalize_loser(self) -> None:
        result = compute_match_scoring(
            winner_pts=1950,
            loser_pts=2200,
            winner_tier=TierEnum.AMATEUR,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.AMATEUR,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
        )

        assert result.winner_delta == ScoreDelta(
            total=162, base=100, upset_bonus=50, elo_bonus=12
        )
        assert result.loser_delta == ScoreDelta(total=-50, penalty=-50)
        assert result.winner_new_pts == 2112
        assert result.loser_new_pts == 2150
        assert result.winner_new_tier == TierEnum.INTERMEDIATE
        assert result.loser_new_tier == TierEnum.INTERMEDIATE
        assert result.winner_tier_crossed is True
        assert result.loser_tier_crossed is False

    def test_loser_floor_prevents_drop_below_registration_tier(self) -> None:
        result = compute_match_scoring(
            winner_pts=1900,
            loser_pts=2010,
            winner_tier=TierEnum.AMATEUR,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.AMATEUR,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
        )

        assert result.loser_delta == ScoreDelta(total=-50, penalty=-50)
        assert result.loser_new_pts == 2000
        assert result.loser_new_tier == TierEnum.INTERMEDIATE
        assert result.loser_tier_crossed is False

    def test_retired_match_returns_zero_deltas(self) -> None:
        result = compute_match_scoring(
            winner_pts=2100,
            loser_pts=2050,
            winner_tier=TierEnum.INTERMEDIATE,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.INTERMEDIATE,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
            retired=True,
        )

        assert result.winner_delta == ScoreDelta(total=0)
        assert result.loser_delta == ScoreDelta(total=0)
        assert result.winner_new_pts == 2100
        assert result.loser_new_pts == 2050
        assert result.winner_new_tier == TierEnum.INTERMEDIATE
        assert result.loser_new_tier == TierEnum.INTERMEDIATE
        assert result.winner_tier_crossed is False
        assert result.loser_tier_crossed is False
