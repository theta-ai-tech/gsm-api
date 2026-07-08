"""Unit tests for the partner-invite claim hook in OnboardingService."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.models.enums import LevelEnum, SportEnum
from app.models.onboarding import RegisterMeRequest
from app.models.user import PrivateUserProfile
from app.services.league_service import LeagueService
from app.services.onboarding_service import OnboardingService

_UID = "user_new"
_TOKEN_EMAIL = "Newbie@Example.com"


def _tier_config() -> MagicMock:
    cfg = MagicMock()
    cfg.get_floor.return_value = 1500
    return cfg


def _request() -> RegisterMeRequest:
    return RegisterMeRequest(
        name="New User",
        sports=[SportEnum.PADEL],
        levels={"padel": LevelEnum.INTERMEDIATE},
        area=1,
    )


def _profile() -> PrivateUserProfile:
    return PrivateUserProfile.model_construct(
        uid=_UID, name="New User", email=_TOKEN_EMAIL
    )


def _make_service(
    league_service: LeagueService | None,
) -> tuple[OnboardingService, MagicMock]:
    users_repo = MagicMock()
    users_repo.get_private_profile.return_value = _profile()
    tier_config_repo = MagicMock()
    tier_config_repo.get.return_value = _tier_config()
    svc = OnboardingService(users_repo, tier_config_repo, league_service)
    return svc, users_repo


def test_claim_called_with_resolved_email():
    league_service = MagicMock(spec=LeagueService)
    svc, users_repo = _make_service(league_service)

    svc.register_me(_UID, _TOKEN_EMAIL, None, _request())

    users_repo.create_profile.assert_called_once()
    league_service.claim_partner_invites.assert_called_once_with(_UID, _TOKEN_EMAIL)


def test_claim_failure_does_not_fail_registration():
    league_service = MagicMock(spec=LeagueService)
    league_service.claim_partner_invites.side_effect = RuntimeError("boom")
    svc, users_repo = _make_service(league_service)

    profile = svc.register_me(_UID, _TOKEN_EMAIL, None, _request())

    assert profile is not None
    users_repo.create_profile.assert_called_once()


def test_register_writes_normalized_email_lower():
    """The doc must carry emailLower (the case-insensitive match key used by
    find_uid_by_email) alongside the casing-preserving email field."""
    svc, users_repo = _make_service(None)

    svc.register_me(_UID, _TOKEN_EMAIL, None, _request())

    _, doc = users_repo.create_profile.call_args.args
    assert doc["email"] == _TOKEN_EMAIL
    assert doc["emailLower"] == "newbie@example.com"


def test_no_league_service_skips_claim():
    svc, users_repo = _make_service(None)
    profile = svc.register_me(_UID, _TOKEN_EMAIL, None, _request())
    assert profile is not None
