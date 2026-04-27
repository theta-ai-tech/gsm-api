"""Unit tests for DBL-4: Offer + SendOfferRequest doubles validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.enums import (
    MatchTypeEnum,
    OfferStatusEnum,
    SportEnum,
)
from app.models.play import Offer, SendOfferRequest


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _offer(**overrides: object) -> Offer:
    base: dict[str, object] = {
        "offer_id": "offer1",
        "from_uid": "alice",
        "from_name": "Alice",
        "to_uid": "bob",
        "to_name": "Bob",
        "sport": SportEnum.TENNIS,
        "proposed_time": _future(),
        "status": OfferStatusEnum.PENDING,
        "expires_at": _future(),
        "created_at": _now(),
    }
    base.update(overrides)
    return Offer(**base)  # type: ignore[arg-type]


class TestSendOfferRequestDefaults:
    def test_singles_default_when_unspecified(self) -> None:
        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.TENNIS,
            proposed_time=_future(),
        )
        assert request.match_type == MatchTypeEnum.SINGLES
        assert request.partner_uid is None


class TestSendOfferRequestValidation:
    def test_doubles_with_partner_is_valid(self) -> None:
        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
            proposed_time=_future(),
        )
        assert request.match_type == MatchTypeEnum.DOUBLES
        assert request.partner_uid == "charlie"

    def test_doubles_without_partner_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
                proposed_time=_future(),
            )
        assert "partner_uid" in str(exc_info.value)

    def test_singles_with_partner_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.TENNIS,
                match_type=MatchTypeEnum.SINGLES,
                partner_uid="charlie",
                proposed_time=_future(),
            )
        assert "singles offer" in str(exc_info.value)


class TestOfferModelDefaults:
    def test_singles_default_when_unspecified(self) -> None:
        offer = _offer()
        assert offer.match_type == MatchTypeEnum.SINGLES
        assert offer.partner_uid is None


class TestOfferModelValidation:
    def test_doubles_with_partner_is_valid(self) -> None:
        offer = _offer(
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
        )
        assert offer.match_type == MatchTypeEnum.DOUBLES
        assert offer.partner_uid == "charlie"

    def test_doubles_without_partner_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _offer(
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
            )
        assert "partner_uid" in str(exc_info.value)

    def test_singles_with_partner_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _offer(
                match_type=MatchTypeEnum.SINGLES,
                partner_uid="charlie",
            )
        assert "singles offer" in str(exc_info.value)
