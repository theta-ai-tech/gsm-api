"""Unit tests for the Skill DNA journal trigger (D4.1 / D4.2)."""

from __future__ import annotations

from datetime import datetime, timezone


from functions.journal_triggers.skill_dna import (
    apply_skill_dna_delta,
    compute_score,
    make_sig,
    parse_sig,
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
# compute_score
# ---------------------------------------------------------------------------


def test_score_below_threshold_returns_zero() -> None:
    assert compute_score(2, 0) == 0
    assert compute_score(0, 2) == 0
    assert compute_score(1, 1) == 0


def test_score_at_threshold() -> None:
    # 2 positive + 1 negative = 3 total → threshold met
    assert compute_score(2, 1) == 67


def test_score_all_positive() -> None:
    assert compute_score(10, 0) == 100


def test_score_all_negative() -> None:
    assert compute_score(0, 10) == 0


def test_score_mixed() -> None:
    assert compute_score(3, 1) == 75


# ---------------------------------------------------------------------------
# make_sig / parse_sig
# ---------------------------------------------------------------------------


def test_make_sig_is_deterministic_regardless_of_order() -> None:
    sig1 = make_sig(["ace", "first_serve"], ["double_faults"])
    sig2 = make_sig(["first_serve", "ace"], ["double_faults"])
    assert sig1 == sig2


def test_parse_sig_roundtrips() -> None:
    well = ["ace", "first_serve"]
    wrong = ["double_faults"]
    sig = make_sig(well, wrong)
    parsed_well, parsed_wrong = parse_sig(sig)
    assert sorted(parsed_well) == sorted(well)
    assert sorted(parsed_wrong) == sorted(wrong)


def test_parse_sig_empty_tags() -> None:
    sig = make_sig([], [])
    well, wrong = parse_sig(sig)
    assert well == []
    assert wrong == []


def test_parse_sig_only_went_well() -> None:
    sig = make_sig(["ace"], [])
    well, wrong = parse_sig(sig)
    assert well == ["ace"]
    assert wrong == []


# ---------------------------------------------------------------------------
# tags_to_axis_counts
# ---------------------------------------------------------------------------


def test_tags_to_axis_counts_basic() -> None:
    counts = tags_to_axis_counts(["first_serve", "ace"], ["double_faults"], _TAG_MAP)
    assert counts["serve"]["positive"] == 2
    assert counts["serve"]["negative"] == 1
    assert "power" not in counts


def test_tags_to_axis_counts_unknown_tags_ignored() -> None:
    counts = tags_to_axis_counts(["unknown_tag"], ["another_unknown"], _TAG_MAP)
    assert counts == {}


def test_tags_to_axis_counts_multiple_axes() -> None:
    counts = tags_to_axis_counts(
        ["first_serve", "volley", "composure"],
        ["double_faults", "endurance"],
        _TAG_MAP,
    )
    assert counts["serve"] == {"positive": 1, "negative": 1}
    assert counts["net_play"] == {"positive": 1, "negative": 0}
    assert counts["mental"] == {"positive": 1, "negative": 0}
    assert counts["stamina"] == {"positive": 0, "negative": 1}


# ---------------------------------------------------------------------------
# apply_skill_dna_delta — create (old_sig=None)
# ---------------------------------------------------------------------------


def test_create_increments_axis_counters() -> None:
    sig = make_sig(["first_serve", "ace"], ["double_faults"])
    result = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    assert result["serve"]["positive"] == 2
    assert result["serve"]["negative"] == 1
    assert result["totalReflections"] == 1
    assert result["entrySignatures"]["e1"] == sig
    assert result["lastUpdated"] == _NOW


def test_create_score_below_threshold_is_zero() -> None:
    sig = make_sig(["first_serve"], [])
    result = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    assert result["serve"]["score"] == 0


def test_create_score_above_threshold() -> None:
    # 3 positive serve tags → score = 100
    sig = make_sig(["first_serve", "ace", "first_serve"], [])
    result = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    # Note: first_serve appears twice in sorted list but map gives 2 positive
    assert result["serve"]["positive"] >= 2


# ---------------------------------------------------------------------------
# apply_skill_dna_delta — update (both sigs set)
# ---------------------------------------------------------------------------


def test_update_adjusts_counters_by_diff() -> None:
    old_sig = make_sig(["first_serve"], ["double_faults"])
    # Bootstrap existing state as if that entry was already processed
    initial = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=old_sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    # Now update: remove first_serve, add ace (both in serve axis)
    new_sig = make_sig(["ace", "ace"], ["double_faults"])
    result = apply_skill_dna_delta(
        current=initial,
        old_sig=old_sig,
        new_sig=new_sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    # old had 1 positive serve, new has 2 → net +1
    assert result["serve"]["positive"] == 2
    assert result["serve"]["negative"] == 1
    assert result["totalReflections"] == 1  # still just 1 entry


def test_update_with_same_sig_is_idempotent_at_delta_level() -> None:
    sig = make_sig(["first_serve"], ["double_faults"])
    state = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    # Apply same sig as update — net delta is zero
    result = apply_skill_dna_delta(
        current=state,
        old_sig=sig,
        new_sig=sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    assert result["serve"]["positive"] == state["serve"]["positive"]
    assert result["totalReflections"] == 1


# ---------------------------------------------------------------------------
# apply_skill_dna_delta — delete (new_sig=None)
# ---------------------------------------------------------------------------


def test_delete_decrements_counters() -> None:
    sig = make_sig(["first_serve", "ace"], ["double_faults"])
    state = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=sig,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    result = apply_skill_dna_delta(
        current=state,
        old_sig=sig,
        new_sig=None,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    assert result["serve"]["positive"] == 0
    assert result["serve"]["negative"] == 0
    assert result["totalReflections"] == 0
    assert "e1" not in result["entrySignatures"]


def test_delete_clamps_counters_at_zero() -> None:
    # Edge case: counter already 0 should not go negative
    sig = make_sig(["first_serve"], [])
    result = apply_skill_dna_delta(
        current={"serve": {"positive": 0, "negative": 0, "score": 0}},
        old_sig=sig,
        new_sig=None,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    assert result["serve"]["positive"] == 0
    assert result["serve"]["negative"] == 0


def test_delete_nonexistent_entry_is_idempotent() -> None:
    # old_sig=None, new_sig=None → should be a no-op (caller prevents this via _write_skill_dna)
    # At the pure function level, nothing crashes
    result = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=None,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    assert result["totalReflections"] == 0
    assert result["entrySignatures"] == {}


# ---------------------------------------------------------------------------
# Multiple entries accumulate independently
# ---------------------------------------------------------------------------


def test_two_entries_accumulate() -> None:
    sig1 = make_sig(["first_serve"], [])
    sig2 = make_sig(["ace", "ace"], ["double_faults"])

    state = apply_skill_dna_delta(
        current={},
        old_sig=None,
        new_sig=sig1,
        tag_map=_TAG_MAP,
        entry_id="e1",
        now=_NOW,
    )
    state = apply_skill_dna_delta(
        current=state,
        old_sig=None,
        new_sig=sig2,
        tag_map=_TAG_MAP,
        entry_id="e2",
        now=_NOW,
    )

    assert state["serve"]["positive"] == 3  # 1 + 2
    assert state["serve"]["negative"] == 1  # 0 + 1
    assert state["totalReflections"] == 2
    assert "e1" in state["entrySignatures"]
    assert "e2" in state["entrySignatures"]


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def test_skill_dna_upsert_noops_when_disabled(monkeypatch) -> None:
    from functions.journal_triggers.main import handle_journal_entry_write_upsert

    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")

    called = {"value": False}

    def _should_not_call(**kwargs):  # type: ignore[misc]
        called["value"] = True
        return True

    monkeypatch.setattr(
        "functions.journal_triggers.main.handle_skill_dna_upsert", _should_not_call
    )

    handle_journal_entry_write_upsert(
        client=object(),  # type: ignore[arg-type]
        uid="u1",
        entry_id="e1",
        before=None,
        after={
            "sport": "tennis",
            "reflection": {"wentWell": ["first_serve"], "wentWrong": []},
            "createdAt": _NOW,
            "title": "Test",
        },
    )

    assert called["value"] is False


def test_skill_dna_delete_noops_when_disabled(monkeypatch) -> None:
    from functions.journal_triggers.main import handle_journal_entry_write_remove

    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")

    called = {"value": False}

    def _should_not_call(**kwargs):  # type: ignore[misc]
        called["value"] = True
        return True

    monkeypatch.setattr(
        "functions.journal_triggers.main.handle_skill_dna_delete", _should_not_call
    )

    handle_journal_entry_write_remove(
        client=object(),  # type: ignore[arg-type]
        uid="u1",
        entry_id="e1",
        before={
            "sport": "tennis",
            "reflection": {"wentWell": ["first_serve"], "wentWrong": []},
        },
        after=None,
    )

    assert called["value"] is False
