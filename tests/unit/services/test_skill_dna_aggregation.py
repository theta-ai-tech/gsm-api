"""Unit tests for Skill DNA aggregation logic (LAB-9).

Covers:
- Single tag maps to correct axis
- Unknown tags are ignored
- Score calculation (8 positive + 2 negative -> score 80)
- Minimum threshold (fewer than 3 data points -> score 0)
- Multiple sports tracked independently
- _build_axes response shaping
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.skill_dna import SkillAxisData, SportSkillDna
from app.routers.lab import _build_axes
from functions.journal_triggers.skill_dna import (
    apply_skill_dna_delta,
    compute_score,
    make_sig,
    tags_to_axis_counts,
)

_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

_TAG_MAP = {
    "first_serve": "serve",
    "double_faults": "serve",
    "ace": "serve",
    "forehand_winner": "power",
    "backhand_winner": "power",
    "net_approach": "net_play",
    "volley": "net_play",
    "endurance": "stamina",
    "fitness": "stamina",
    "concentration": "mental",
    "composure": "mental",
    "tiebreak": "mental",
}


# ---------------------------------------------------------------------------
# Single tag maps to correct axis
# ---------------------------------------------------------------------------


class TestSingleTagMapping:
    def test_serve_tag_maps_to_serve_axis(self) -> None:
        counts = tags_to_axis_counts(["first_serve"], [], _TAG_MAP)
        assert "serve" in counts
        assert counts["serve"]["positive"] == 1

    def test_power_tag_maps_to_power_axis(self) -> None:
        counts = tags_to_axis_counts(["forehand_winner"], [], _TAG_MAP)
        assert "power" in counts
        assert counts["power"]["positive"] == 1

    def test_net_play_tag_maps_to_net_play_axis(self) -> None:
        counts = tags_to_axis_counts(["volley"], [], _TAG_MAP)
        assert "net_play" in counts
        assert counts["net_play"]["positive"] == 1

    def test_stamina_tag_maps_to_stamina_axis(self) -> None:
        counts = tags_to_axis_counts(["endurance"], [], _TAG_MAP)
        assert "stamina" in counts
        assert counts["stamina"]["positive"] == 1

    def test_mental_tag_maps_to_mental_axis(self) -> None:
        counts = tags_to_axis_counts(["concentration"], [], _TAG_MAP)
        assert "mental" in counts
        assert counts["mental"]["positive"] == 1

    def test_negative_tag_maps_to_correct_axis(self) -> None:
        counts = tags_to_axis_counts([], ["double_faults"], _TAG_MAP)
        assert "serve" in counts
        assert counts["serve"]["negative"] == 1
        assert counts["serve"]["positive"] == 0


# ---------------------------------------------------------------------------
# Unknown tags are ignored
# ---------------------------------------------------------------------------


class TestUnknownTagsIgnored:
    def test_unknown_positive_tag_ignored(self) -> None:
        counts = tags_to_axis_counts(["nonexistent_skill"], [], _TAG_MAP)
        assert counts == {}

    def test_unknown_negative_tag_ignored(self) -> None:
        counts = tags_to_axis_counts([], ["nonexistent_skill"], _TAG_MAP)
        assert counts == {}

    def test_mix_of_known_and_unknown_tags(self) -> None:
        counts = tags_to_axis_counts(
            ["first_serve", "unknown_tag"], ["another_unknown"], _TAG_MAP
        )
        assert "serve" in counts
        assert counts["serve"]["positive"] == 1
        assert len(counts) == 1  # only serve axis created


# ---------------------------------------------------------------------------
# Score calculation: 8 positive + 2 negative -> score 80
# ---------------------------------------------------------------------------


class TestScoreCalculation:
    def test_8_positive_2_negative_equals_80(self) -> None:
        assert compute_score(8, 2) == 80

    def test_all_10_positive_equals_100(self) -> None:
        assert compute_score(10, 0) == 100

    def test_all_10_negative_equals_0(self) -> None:
        assert compute_score(0, 10) == 0

    def test_5_and_5_equals_50(self) -> None:
        assert compute_score(5, 5) == 50

    def test_score_rounds_correctly(self) -> None:
        # 1/3 = 33.33...% -> rounds to 33
        assert compute_score(1, 2) == 33

    def test_score_integrated_via_apply_delta(self) -> None:
        """8 positive + 2 negative serve tags -> score 80 via full pipeline."""
        well = ["first_serve"] * 8
        wrong = ["double_faults"] * 2
        sig = make_sig(well, wrong)
        result = apply_skill_dna_delta(
            current={},
            old_sig=None,
            new_sig=sig,
            tag_map=_TAG_MAP,
            entry_id="e1",
            now=_NOW,
        )
        assert result["serve"]["positive"] == 8
        assert result["serve"]["negative"] == 2
        assert result["serve"]["score"] == 80


# ---------------------------------------------------------------------------
# Minimum threshold: fewer than 3 data points -> score = 0
# ---------------------------------------------------------------------------


class TestMinimumThreshold:
    def test_zero_data_points_score_zero(self) -> None:
        assert compute_score(0, 0) == 0

    def test_one_data_point_score_zero(self) -> None:
        assert compute_score(1, 0) == 0

    def test_two_data_points_score_zero(self) -> None:
        assert compute_score(2, 0) == 0
        assert compute_score(1, 1) == 0
        assert compute_score(0, 2) == 0

    def test_three_data_points_score_computed(self) -> None:
        assert compute_score(2, 1) == 67
        assert compute_score(3, 0) == 100

    def test_threshold_via_apply_delta(self) -> None:
        """Entry with only 2 serve tags -> score still 0 (below threshold)."""
        sig = make_sig(["first_serve", "ace"], [])
        result = apply_skill_dna_delta(
            current={},
            old_sig=None,
            new_sig=sig,
            tag_map=_TAG_MAP,
            entry_id="e1",
            now=_NOW,
        )
        assert result["serve"]["positive"] == 2
        assert result["serve"]["score"] == 0  # below threshold of 3

    def test_build_axes_marks_insufficient(self) -> None:
        """Axes with fewer than 3 data points appear in insufficient list."""
        dna = SportSkillDna(
            serve=SkillAxisData(positive=2, negative=0, score=0),
            power=SkillAxisData(positive=5, negative=3, score=63),
            totalReflections=3,
        )
        axes, insufficient = _build_axes(dna)
        assert "serve" in insufficient  # 2 + 0 = 2 < 3
        assert "power" not in insufficient  # 5 + 3 = 8 >= 3
        assert len(axes) == 2


# ---------------------------------------------------------------------------
# Multiple sports tracked independently
# ---------------------------------------------------------------------------


class TestMultipleSportsIndependent:
    def test_two_sports_do_not_share_state(self) -> None:
        """Applying deltas for two different sports keeps their data separate."""
        tennis_sig = make_sig(["first_serve", "ace", "ace"], [])
        padel_sig = make_sig(["volley", "net_approach", "net_approach"], [])

        tennis_dna = apply_skill_dna_delta(
            current={},
            old_sig=None,
            new_sig=tennis_sig,
            tag_map=_TAG_MAP,
            entry_id="e1",
            now=_NOW,
        )
        padel_dna = apply_skill_dna_delta(
            current={},
            old_sig=None,
            new_sig=padel_sig,
            tag_map=_TAG_MAP,
            entry_id="e2",
            now=_NOW,
        )

        # Tennis only has serve data
        assert tennis_dna["serve"]["positive"] == 3
        assert (
            "net_play" not in tennis_dna
            or tennis_dna.get("net_play", {}).get("positive", 0) == 0
        )

        # Padel only has net_play data
        assert padel_dna["net_play"]["positive"] == 3
        assert (
            "serve" not in padel_dna
            or padel_dna.get("serve", {}).get("positive", 0) == 0
        )

    def test_sport_accumulation_does_not_leak(self) -> None:
        """Updating one sport's DNA does not affect the other."""
        sig1 = make_sig(["first_serve"] * 5, ["double_faults"] * 2)
        sport_a = apply_skill_dna_delta(
            current={},
            old_sig=None,
            new_sig=sig1,
            tag_map=_TAG_MAP,
            entry_id="e1",
            now=_NOW,
        )

        sig2 = make_sig(["endurance"] * 4, ["fitness"] * 1)
        sport_b = apply_skill_dna_delta(
            current={},
            old_sig=None,
            new_sig=sig2,
            tag_map=_TAG_MAP,
            entry_id="e2",
            now=_NOW,
        )

        # Each sport has its own isolated DNA dict
        assert "serve" in sport_a
        assert (
            "stamina" not in sport_a
            or sport_a.get("stamina", {}).get("positive", 0) == 0
        )
        assert "stamina" in sport_b
        assert (
            "serve" not in sport_b or sport_b.get("serve", {}).get("positive", 0) == 0
        )

        # Scores computed correctly per-sport
        assert sport_a["serve"]["score"] == compute_score(5, 2)  # 71
        assert sport_b["stamina"]["score"] == compute_score(4, 1)  # 80


# ---------------------------------------------------------------------------
# _build_axes response shaping
# ---------------------------------------------------------------------------


class TestBuildAxes:
    def test_all_axes_populated(self) -> None:
        dna = SportSkillDna(
            serve=SkillAxisData(positive=10, negative=2, score=83),
            power=SkillAxisData(positive=5, negative=3, score=63),
            net_play=SkillAxisData(positive=4, negative=1, score=80),
            stamina=SkillAxisData(positive=6, negative=2, score=75),
            mental=SkillAxisData(positive=7, negative=1, score=88),
            totalReflections=10,
        )
        axes, insufficient = _build_axes(dna)
        assert len(axes) == 5
        assert axes["serve"].score == 83
        assert axes["power"].positive == 5
        assert insufficient == []

    def test_none_axes_omitted(self) -> None:
        dna = SportSkillDna(
            serve=SkillAxisData(positive=5, negative=1, score=83),
            totalReflections=2,
        )
        axes, insufficient = _build_axes(dna)
        assert "serve" in axes
        assert "power" not in axes
        assert "net_play" not in axes
        assert len(axes) == 1

    def test_empty_dna(self) -> None:
        dna = SportSkillDna(totalReflections=0)
        axes, insufficient = _build_axes(dna)
        assert axes == {}
        assert insufficient == []
