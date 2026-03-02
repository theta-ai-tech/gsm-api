from app.models.enums import TierEnum
from app.models.tier import TierThreshold
from app.services.tier_service import get_tier


def _default_thresholds() -> list[TierThreshold]:
    return [
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
    ]


class TestGetTier:
    def test_intermediate_mid_range(self) -> None:
        assert get_tier(2500, _default_thresholds()) == "intermediate"

    def test_competitive_above_4000(self) -> None:
        assert get_tier(4200, _default_thresholds()) == "competitive"

    def test_below_all_ranges_falls_back_to_lowest(self) -> None:
        assert get_tier(999, _default_thresholds()) == "amateur"

    def test_amateur_lower_boundary(self) -> None:
        assert get_tier(1000, _default_thresholds()) == "amateur"

    def test_amateur_upper_boundary(self) -> None:
        assert get_tier(1999, _default_thresholds()) == "amateur"

    def test_advanced_lower_boundary(self) -> None:
        assert get_tier(3000, _default_thresholds()) == "advanced"

    def test_advanced_upper_boundary(self) -> None:
        assert get_tier(3999, _default_thresholds()) == "advanced"

    def test_competitive_lower_boundary(self) -> None:
        assert get_tier(4000, _default_thresholds()) == "competitive"

    def test_competitive_very_high(self) -> None:
        assert get_tier(99999, _default_thresholds()) == "competitive"

    def test_zero_points_falls_back_to_lowest(self) -> None:
        assert get_tier(0, _default_thresholds()) == "amateur"
