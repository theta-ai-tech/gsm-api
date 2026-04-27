"""Unit tests for DBL-3: Broadcast model doubles support and validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    MatchTypeEnum,
    SportEnum,
)
from app.models.play import (
    Broadcast,
    BroadcastLocation,
    CreateBroadcastRequest,
)


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request(**overrides: object) -> CreateBroadcastRequest:
    base: dict[str, object] = {
        "sport": SportEnum.TENNIS,
        "availability": AvailabilityEnum.TODAY,
        "court_status": CourtStatusEnum.NEED_COURT,
        "expires_at": _future(),
        "location": BroadcastLocation(area=10001),
    }
    base.update(overrides)
    return CreateBroadcastRequest(**base)  # type: ignore[arg-type]


def _broadcast(**overrides: object) -> Broadcast:
    base: dict[str, object] = {
        "broadcast_id": "b1",
        "owner_uid": "u1",
        "owner_name": "Alice",
        "sport": SportEnum.TENNIS,
        "availability": AvailabilityEnum.TODAY,
        "court_status": CourtStatusEnum.NEED_COURT,
        "status": BroadcastStatusEnum.ACTIVE,
        "expires_at": _future(),
        "created_at": _now(),
        "location": BroadcastLocation(area=10001),
    }
    base.update(overrides)
    return Broadcast(**base)  # type: ignore[arg-type]


class TestCreateBroadcastRequestDefaults:
    def test_defaults_to_singles_find_opponent(self) -> None:
        req = _request()
        assert req.match_type == MatchTypeEnum.SINGLES
        assert req.broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
        assert req.partner_uid is None


class TestCreateBroadcastRequestValidation:
    def test_singles_find_opponent_no_partner_is_valid(self) -> None:
        req = _request(
            match_type=MatchTypeEnum.SINGLES,
            broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
        )
        assert req.partner_uid is None

    def test_doubles_find_opponent_with_partner_is_valid(self) -> None:
        req = _request(
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
            partner_uid="user_partner",
        )
        assert req.partner_uid == "user_partner"

    def test_doubles_find_opponent_without_partner_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires partner_uid"):
            _request(
                match_type=MatchTypeEnum.DOUBLES,
                broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
                partner_uid=None,
            )

    def test_doubles_find_fourth_with_partner_is_valid(self) -> None:
        req = _request(
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
            partner_uid="user_partner",
        )
        assert req.partner_uid == "user_partner"

    def test_doubles_find_fourth_without_partner_is_valid(self) -> None:
        """Solo player looking for 3 others is allowed."""
        req = _request(
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
        )
        assert req.partner_uid is None

    def test_singles_find_fourth_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="find_fourth requires match_type=doubles"
        ):
            _request(
                match_type=MatchTypeEnum.SINGLES,
                broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
            )


class TestBroadcastModelDefaults:
    def test_legacy_broadcast_defaults_to_singles_find_opponent(self) -> None:
        b = _broadcast()
        assert b.match_type == MatchTypeEnum.SINGLES
        assert b.broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
        assert b.partner_uid is None


class TestBroadcastModelValidation:
    def test_doubles_find_opponent_without_partner_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires partner_uid"):
            _broadcast(
                match_type=MatchTypeEnum.DOUBLES,
                broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
                partner_uid=None,
            )

    def test_singles_find_fourth_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="find_fourth requires match_type=doubles"
        ):
            _broadcast(
                match_type=MatchTypeEnum.SINGLES,
                broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
            )

    def test_doubles_find_fourth_without_partner_is_valid(self) -> None:
        b = _broadcast(
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
        )
        assert b.partner_uid is None
