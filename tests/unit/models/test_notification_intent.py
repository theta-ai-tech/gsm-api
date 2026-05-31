"""Unit tests for PlayNotificationIntent model validation."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.enums import PlayNotificationIntentTypeEnum
from app.models.notification import PlayNotificationIntent

_NOW = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc)


def _base_kwargs(**overrides) -> dict:
    return {
        "type": PlayNotificationIntentTypeEnum.INCOMING_OFFER,
        "target_uid": "user_abc",
        "title": "New match offer",
        "body": "Someone wants to play",
        "offer_id": "offer_123",
        "dedupe_key": "incoming_offer:offer_123",
        "created_at": _NOW,
        **overrides,
    }


class TestValidConstruction:
    def test_incoming_offer_valid(self):
        intent = PlayNotificationIntent(**_base_kwargs())
        assert intent.type == PlayNotificationIntentTypeEnum.INCOMING_OFFER
        assert intent.offer_id == "offer_123"
        assert intent.match_id is None

    def test_match_scheduled_valid(self):
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.MATCH_SCHEDULED,
            target_uid="user_abc",
            title="Match confirmed!",
            body="Your match is on Jun 01",
            match_id="match_xyz",
            dedupe_key="match_scheduled:match_xyz:user_abc",
            created_at=_NOW,
        )
        assert intent.type == PlayNotificationIntentTypeEnum.MATCH_SCHEDULED
        assert intent.match_id == "match_xyz"
        assert intent.offer_id is None

    def test_score_confirm_required_valid(self):
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.SCORE_CONFIRM_REQUIRED,
            target_uid="user_def",
            title="Score submitted",
            body="Confirm the match result",
            match_id="match_xyz",
            dedupe_key="score_confirm_required:match_xyz:user_def",
            created_at=_NOW,
        )
        assert intent.type == PlayNotificationIntentTypeEnum.SCORE_CONFIRM_REQUIRED
        assert intent.match_id == "match_xyz"

    def test_intent_id_defaults_to_empty_string(self):
        intent = PlayNotificationIntent(**_base_kwargs())
        assert intent.intent_id == ""

    def test_optional_broadcast_id_can_be_set(self):
        intent = PlayNotificationIntent(**_base_kwargs(broadcast_id="bc_001"))
        assert intent.broadcast_id == "bc_001"


class TestRequiredFieldValidation:
    def test_incoming_offer_without_offer_id_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            PlayNotificationIntent(
                type=PlayNotificationIntentTypeEnum.INCOMING_OFFER,
                target_uid="user_abc",
                title="New offer",
                body="Play?",
                dedupe_key="incoming_offer:missing",
                created_at=_NOW,
            )
        assert "offer_id" in str(exc_info.value)

    def test_match_scheduled_without_match_id_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            PlayNotificationIntent(
                type=PlayNotificationIntentTypeEnum.MATCH_SCHEDULED,
                target_uid="user_abc",
                title="Match confirmed",
                body="Play!",
                dedupe_key="match_scheduled:missing:user_abc",
                created_at=_NOW,
            )
        assert "match_id" in str(exc_info.value)

    def test_score_confirm_required_without_match_id_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            PlayNotificationIntent(
                type=PlayNotificationIntentTypeEnum.SCORE_CONFIRM_REQUIRED,
                target_uid="user_def",
                title="Score submitted",
                body="Confirm",
                dedupe_key="score_confirm_required:missing:user_def",
                created_at=_NOW,
            )
        assert "match_id" in str(exc_info.value)
