from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.enums import TierEnum
from app.models.tier import TierConfig, TierThreshold


def _sample_thresholds() -> list[TierThreshold]:
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


class TestTierThreshold:
    def test_valid_construction(self) -> None:
        t = TierThreshold(
            tier=TierEnum.AMATEUR,
            min_pts=1000,
            max_pts=1999,
            label="Amateur",
            color="#8B8B8B",
        )
        assert t.tier == TierEnum.AMATEUR
        assert t.min_pts == 1000
        assert t.max_pts == 1999
        assert t.label == "Amateur"
        assert t.color == "#8B8B8B"

    def test_max_pts_none_for_open_ended_tier(self) -> None:
        t = TierThreshold(
            tier=TierEnum.COMPETITIVE,
            min_pts=4000,
            max_pts=None,
            label="Competitive",
            color="#FF6B35",
        )
        assert t.max_pts is None

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TierThreshold(
                tier=TierEnum.AMATEUR,
                min_pts=1000,
                max_pts=1999,
                label="Amateur",
                color="#8B8B8B",
                bonus=True,  # type: ignore[call-arg]
            )

    def test_camel_case_alias(self) -> None:
        t = TierThreshold.model_validate(
            {
                "tier": "amateur",
                "minPts": 1000,
                "maxPts": 1999,
                "label": "Amateur",
                "color": "#8B8B8B",
            }
        )
        assert t.min_pts == 1000
        assert t.max_pts == 1999


class TestTierConfig:
    def test_valid_construction(self) -> None:
        thresholds = _sample_thresholds()
        config = TierConfig(
            thresholds=thresholds,
            version=1,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(config.thresholds) == 4
        assert config.version == 1

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TierConfig(
                thresholds=_sample_thresholds(),
                version=1,
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                extra_field="bad",  # type: ignore[call-arg]
            )

    def test_camel_case_alias(self) -> None:
        config = TierConfig.model_validate(
            {
                "thresholds": [
                    {
                        "tier": "amateur",
                        "minPts": 1000,
                        "maxPts": 1999,
                        "label": "Amateur",
                        "color": "#8B8B8B",
                    },
                ],
                "version": 1,
                "updatedAt": "2026-01-01T00:00:00Z",
            }
        )
        assert config.thresholds[0].min_pts == 1000
        assert config.updated_at.tzinfo is not None

    def test_get_floor_returns_threshold_min_points(self) -> None:
        config = TierConfig(
            thresholds=_sample_thresholds(),
            version=1,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        assert config.get_floor(TierEnum.INTERMEDIATE) == 2000
