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

    def test_same_tier_winner_has_more_pts_awards_base_only(self) -> None:
        # Winner already has more pts — still just base, no upset bonus
        assert calculate_score_delta(
            2500, 2100, TierEnum.INTERMEDIATE, TierEnum.INTERMEDIATE
        ) == ScoreDelta(total=100, base=100)

    def test_upset_adds_bonus_and_elo_component(self) -> None:
        assert calculate_score_delta(
            2400, 3000, TierEnum.INTERMEDIATE, TierEnum.ADVANCED
        ) == (ScoreDelta(total=180, base=100, upset_bonus=50, elo_bonus=30))

    def test_upset_large_gap_caps_elo_at_fifty(self) -> None:
        # pts_diff = 3000 - 2000 = 1000 → elo_bonus = floor(1000 * 0.05) = 50
        assert calculate_score_delta(
            2000, 3000, TierEnum.INTERMEDIATE, TierEnum.ADVANCED
        ) == ScoreDelta(total=200, base=100, upset_bonus=50, elo_bonus=50)

    def test_upset_small_gap_gives_small_elo_bonus(self) -> None:
        # pts_diff = 3000 - 2900 = 100 → elo_bonus = floor(100 * 0.05) = 5
        assert calculate_score_delta(
            2900, 3000, TierEnum.INTERMEDIATE, TierEnum.ADVANCED
        ) == ScoreDelta(total=155, base=100, upset_bonus=50, elo_bonus=5)


class TestCalculatePenalty:
    def test_loser_penalty_applies_when_losing_to_lower_tier(self) -> None:
        assert (
            calculate_penalty(2200, 1900, TierEnum.INTERMEDIATE, TierEnum.AMATEUR)
            == -50
        )

    def test_no_penalty_when_losing_to_same_tier(self) -> None:
        assert (
            calculate_penalty(2200, 2400, TierEnum.INTERMEDIATE, TierEnum.INTERMEDIATE)
            == 0
        )

    def test_no_penalty_when_losing_to_higher_tier(self) -> None:
        assert (
            calculate_penalty(2200, 3100, TierEnum.INTERMEDIATE, TierEnum.ADVANCED) == 0
        )


class TestApplyFloor:
    def test_points_below_floor_clamped_to_floor(self) -> None:
        assert apply_floor(1950, TierEnum.INTERMEDIATE, _tier_config()) == 2000

    def test_points_at_floor_unchanged(self) -> None:
        assert apply_floor(2000, TierEnum.INTERMEDIATE, _tier_config()) == 2000

    def test_points_above_floor_unchanged(self) -> None:
        assert apply_floor(2500, TierEnum.INTERMEDIATE, _tier_config()) == 2500


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

    def test_loser_floor_clamps_pts_and_effective_delta_is_actual_change(self) -> None:
        # loser_pts=2010, penalty=-50 → raw=1960 < floor(2000) → clamped to 2000
        # effective delta = 2000 - 2010 = -10 (not the raw -50)
        result = compute_match_scoring(
            winner_pts=1900,
            loser_pts=2010,
            winner_tier=TierEnum.AMATEUR,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.AMATEUR,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
        )

        assert result.loser_delta == ScoreDelta(total=-10, penalty=-50)
        assert result.loser_new_pts == 2000
        assert result.loser_new_tier == TierEnum.INTERMEDIATE
        assert result.loser_tier_crossed is False

    def test_loser_exactly_at_floor_delta_is_zero(self) -> None:
        # loser_pts=2000, penalty=-50 → raw=1950 < floor(2000) → clamped to 2000
        # effective delta = 2000 - 2000 = 0
        result = compute_match_scoring(
            winner_pts=1900,
            loser_pts=2000,
            winner_tier=TierEnum.AMATEUR,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.AMATEUR,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
        )

        assert result.loser_delta == ScoreDelta(total=0, penalty=-50)
        assert result.loser_new_pts == 2000

    def test_loser_above_floor_full_penalty_applied(self) -> None:
        # loser_pts=2050, penalty=-50 → raw=2000 = floor → no clamping needed
        # effective delta = 2000 - 2050 = -50
        result = compute_match_scoring(
            winner_pts=1900,
            loser_pts=2050,
            winner_tier=TierEnum.AMATEUR,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.AMATEUR,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
        )

        assert result.loser_delta == ScoreDelta(total=-50, penalty=-50)
        assert result.loser_new_pts == 2000

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

    def test_walkover_returns_zero_deltas(self) -> None:
        result = compute_match_scoring(
            winner_pts=2100,
            loser_pts=2050,
            winner_tier=TierEnum.INTERMEDIATE,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.INTERMEDIATE,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
            walkover=True,
        )

        assert result.winner_delta == ScoreDelta(total=0)
        assert result.loser_delta == ScoreDelta(total=0)
        assert result.winner_new_pts == 2100
        assert result.loser_new_pts == 2050
        assert result.winner_tier_crossed is False
        assert result.loser_tier_crossed is False

    def test_winner_crosses_tier_intermediate_to_advanced(self) -> None:
        # winner at 2900 + 100 base = 3000 → crosses into ADVANCED
        result = compute_match_scoring(
            winner_pts=2900,
            loser_pts=2800,
            winner_tier=TierEnum.INTERMEDIATE,
            loser_tier=TierEnum.INTERMEDIATE,
            winner_reg_tier=TierEnum.INTERMEDIATE,
            loser_reg_tier=TierEnum.INTERMEDIATE,
            tier_config=_tier_config(),
        )

        assert result.winner_new_pts == 3000
        assert result.winner_new_tier == TierEnum.ADVANCED
        assert result.winner_tier_crossed is True
        assert result.loser_tier_crossed is False

    def test_both_competitive_same_tier_no_tier_change(self) -> None:
        result = compute_match_scoring(
            winner_pts=4200,
            loser_pts=4100,
            winner_tier=TierEnum.COMPETITIVE,
            loser_tier=TierEnum.COMPETITIVE,
            winner_reg_tier=TierEnum.COMPETITIVE,
            loser_reg_tier=TierEnum.COMPETITIVE,
            tier_config=_tier_config(),
        )

        assert result.winner_delta == ScoreDelta(total=100, base=100)
        assert result.loser_delta == ScoreDelta(total=0)
        assert result.winner_new_pts == 4300
        assert result.loser_new_pts == 4100
        assert result.winner_new_tier == TierEnum.COMPETITIVE
        assert result.loser_new_tier == TierEnum.COMPETITIVE
        assert result.winner_tier_crossed is False
        assert result.loser_tier_crossed is False
