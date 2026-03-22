"""
Unit tests for scouting service — confidence calculation, tag sorting, labels.
"""

from __future__ import annotations

from app.services.scouting_service import compute_confidence, sorted_tag_list, tag_label


class TestComputeConfidence:
    def test_low_when_zero_reports(self) -> None:
        assert compute_confidence(0) == "low"

    def test_low_when_two_reports(self) -> None:
        assert compute_confidence(2) == "low"

    def test_medium_at_three_reports(self) -> None:
        assert compute_confidence(3) == "medium"

    def test_medium_at_seven_reports(self) -> None:
        assert compute_confidence(7) == "medium"

    def test_high_at_eight_reports(self) -> None:
        assert compute_confidence(8) == "high"

    def test_high_at_many_reports(self) -> None:
        assert compute_confidence(100) == "high"


class _FakeTagCount:
    def __init__(self, count: int) -> None:
        self.count = count


class TestSortedTagList:
    def test_sorted_descending_by_count(self) -> None:
        tags: dict[str, object] = {
            "backhand": _FakeTagCount(3),
            "serve": _FakeTagCount(7),
            "stamina": _FakeTagCount(5),
        }
        result = sorted_tag_list(tags)
        assert result == [("serve", 7), ("stamina", 5), ("backhand", 3)]

    def test_empty_dict_returns_empty_list(self) -> None:
        assert sorted_tag_list({}) == []

    def test_single_tag(self) -> None:
        tags: dict[str, object] = {"ace": _FakeTagCount(1)}
        result = sorted_tag_list(tags)
        assert result == [("ace", 1)]


class TestTagLabel:
    def test_known_tag(self) -> None:
        assert tag_label("first_serve") == "First serve"

    def test_known_tag_simple(self) -> None:
        assert tag_label("backhand") == "Backhand"

    def test_unknown_tag_capitalised(self) -> None:
        assert tag_label("drop_shot") == "Drop shot"

    def test_unknown_single_word(self) -> None:
        assert tag_label("lob") == "Lob"

    def test_stamina_set3_label(self) -> None:
        assert tag_label("stamina_set3") == "Late-set stamina"
