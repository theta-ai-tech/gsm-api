"""UT-01: Unit tests for JournalEntry model new fields (DM-01) and request/response models (DM-04)."""

from datetime import datetime, timezone

import pytest

from app.constants import (
    JOURNAL_BODY_MAX,
    JOURNAL_CLIENT_REQUEST_ID_MAX,
    JOURNAL_TAGS_MAX,
    JOURNAL_TITLE_MAX,
)
from app.models.enums import (
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    MatchResultEnum,
    SportEnum,
    TrainingFocusEnum,
)
from app.models.journal import (
    CreateJournalEntryRequest,
    JournalEntry,
    MatchReflection,
    UpdateJournalEntryRequest,
)

NOW = datetime.now(timezone.utc)


# ── JournalEntry ──────────────────────────────────────────────────────────────


class TestJournalEntryModel:
    def test_all_new_fields_validate(self):
        """JournalEntry with all new fields parses and stores correctly."""
        entry = JournalEntry(
            entry_id="e1",
            uid="u1",
            created_at=NOW,
            title="Post-match notes",
            body="Tough match today",
            tags=["forehand"],
            match_id="m1",
            sport=SportEnum.TENNIS,
            visibility=JournalVisibilityEnum.PRIVATE,
            entry_type=JournalEntryTypeEnum.MATCH,
            duration_minutes=None,
            training_focus=[],
            reflection=MatchReflection(
                went_well=["first_serve"],
                went_wrong=["double_faults"],
                opponent_weak=["backhand"],
                opponent_strong=["serve"],
            ),
            score_text="6-4 7-5",
            result=MatchResultEnum.WIN,
        )

        assert entry.entry_type == JournalEntryTypeEnum.MATCH
        assert entry.score_text == "6-4 7-5"
        assert entry.result == MatchResultEnum.WIN
        assert entry.reflection is not None
        assert entry.reflection.went_well == ["first_serve"]
        assert entry.reflection.went_wrong == ["double_faults"]
        assert entry.client_request_id is None
        assert entry.is_deleted is False
        assert entry.deleted_at is None

    def test_backward_compat_defaults(self):
        """JournalEntry without new fields still deserialises with correct defaults."""
        entry = JournalEntry(
            entry_id="e2",
            uid="u1",
            created_at=NOW,
            title="Old entry",
            body="",
            visibility=JournalVisibilityEnum.PRIVATE,
        )

        assert entry.entry_type == JournalEntryTypeEnum.MATCH
        assert entry.duration_minutes is None
        assert entry.training_focus == []
        assert entry.reflection is None
        assert entry.score_text is None
        assert entry.result is None
        assert entry.tags == []
        assert entry.client_request_id is None
        assert entry.is_deleted is False
        assert entry.deleted_at is None


# ── MatchReflection ───────────────────────────────────────────────────────────


class TestMatchReflection:
    def test_validates_string_lists(self):
        """MatchReflection accepts lists of strings for all tag fields."""
        r = MatchReflection(
            went_well=["first_serve", "net_play"],
            went_wrong=["double_faults"],
            opponent_weak=["backhand"],
            opponent_strong=["serve", "footwork"],
        )

        assert r.went_well == ["first_serve", "net_play"]
        assert r.went_wrong == ["double_faults"]
        assert r.opponent_weak == ["backhand"]
        assert r.opponent_strong == ["serve", "footwork"]
        assert r.ai_summary is None
        assert r.reflection_version is None

    def test_all_fields_default_to_empty(self):
        r = MatchReflection()
        assert r.went_well == []
        assert r.went_wrong == []
        assert r.opponent_weak == []
        assert r.opponent_strong == []


# ── CreateJournalEntryRequest ─────────────────────────────────────────────────


class TestCreateJournalEntryRequest:
    def test_match_type_with_match_id(self):
        """Match entry with match_id provided passes without warnings (at runtime)."""
        req = CreateJournalEntryRequest(
            entry_type=JournalEntryTypeEnum.MATCH,
            title="Great win",
            body="Played well",
            match_id="m1",
            sport=SportEnum.TENNIS,
            score_text="6-3 6-2",
            result=MatchResultEnum.WIN,
        )

        assert req.entry_type == JournalEntryTypeEnum.MATCH
        assert req.match_id == "m1"
        assert req.visibility == JournalVisibilityEnum.PRIVATE  # default

    def test_match_type_without_match_id_is_allowed(self):
        """Match entry without match_id warns but does not raise."""
        req = CreateJournalEntryRequest(
            entry_type=JournalEntryTypeEnum.MATCH,
            title="Quick note",
        )
        assert req.match_id is None  # no error raised

    def test_training_type_with_valid_duration(self):
        """Training entry with duration_minutes > 0 validates correctly."""
        req = CreateJournalEntryRequest(
            entry_type=JournalEntryTypeEnum.TRAINING,
            title="Serve session",
            duration_minutes=60,
            training_focus=[TrainingFocusEnum.SERVE, TrainingFocusEnum.FOOTWORK],
        )

        assert req.entry_type == JournalEntryTypeEnum.TRAINING
        assert req.duration_minutes == 60
        assert TrainingFocusEnum.SERVE in req.training_focus

    def test_training_type_missing_duration_raises(self):
        """Training entry without duration_minutes raises ValueError."""
        with pytest.raises(ValueError, match="duration_minutes"):
            CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.TRAINING,
                title="No duration",
            )

    def test_training_type_zero_duration_raises(self):
        with pytest.raises(ValueError, match="duration_minutes"):
            CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.TRAINING,
                duration_minutes=0,
            )

    def test_title_max_length_enforced(self):
        with pytest.raises(Exception):
            CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                title="x" * (JOURNAL_TITLE_MAX + 1),
            )

    def test_body_max_length_enforced(self):
        with pytest.raises(Exception):
            CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                body="y" * (JOURNAL_BODY_MAX + 1),
            )

    def test_tags_max_items_enforced(self):
        with pytest.raises(Exception):
            CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                tags=[f"tag{i}" for i in range(JOURNAL_TAGS_MAX + 1)],
            )

    def test_default_visibility_is_private(self):
        req = CreateJournalEntryRequest(entry_type=JournalEntryTypeEnum.MATCH)
        assert req.visibility == JournalVisibilityEnum.PRIVATE

    def test_client_request_id_max_length_enforced(self):
        with pytest.raises(Exception):
            CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                client_request_id="x" * (JOURNAL_CLIENT_REQUEST_ID_MAX + 1),
            )


# ── UpdateJournalEntryRequest ─────────────────────────────────────────────────


class TestUpdateJournalEntryRequest:
    def test_all_fields_optional(self):
        """UpdateJournalEntryRequest with no fields is valid (all None)."""
        req = UpdateJournalEntryRequest()
        assert req.reflection is None
        assert req.tags is None
        assert req.body is None

    def test_partial_update_validates(self):
        """UpdateJournalEntryRequest with only reflection set is valid."""
        req = UpdateJournalEntryRequest(
            reflection=MatchReflection(went_well=["volley"])
        )
        assert req.reflection is not None
        assert req.reflection.went_well == ["volley"]
        assert req.tags is None
        assert req.body is None


# ── Enum values ───────────────────────────────────────────────────────────────


class TestEnumValues:
    def test_journal_entry_type_enum_values(self):
        assert JournalEntryTypeEnum.MATCH == "match"
        assert JournalEntryTypeEnum.TRAINING == "training"

    def test_training_focus_enum_values(self):
        assert TrainingFocusEnum.SERVE == "serve"
        assert TrainingFocusEnum.VOLLEY == "volley"
        assert TrainingFocusEnum.FOOTWORK == "footwork"
        assert TrainingFocusEnum.BACKHAND == "backhand"
        assert TrainingFocusEnum.CARDIO == "cardio"
        assert TrainingFocusEnum.STRATEGY == "strategy"
