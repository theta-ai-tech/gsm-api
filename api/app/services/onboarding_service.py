import logging
from datetime import datetime, timezone

from app.models.enums import LevelEnum, TierEnum
from app.models.onboarding import RegisterMeRequest
from app.models.user import PrivateUserProfile
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.league_service import LeagueService
from app.utils.contact import normalize_email

logger = logging.getLogger(__name__)


class OnboardingConfigError(RuntimeError):
    """Raised when server-side configuration required for registration is missing or
    invalid (e.g. config/tiers not seeded, or a tier has no configured floor).

    This is a server/environment fault, not a client input problem — callers should
    map it to 5xx, never 4xx. Deliberately NOT a ValueError subclass so it is never
    accidentally swept up by a bare `except ValueError` clause.
    """


LEVEL_TO_TIER: dict[LevelEnum, TierEnum] = {
    LevelEnum.BEGINNER: TierEnum.AMATEUR,
    LevelEnum.INTERMEDIATE: TierEnum.INTERMEDIATE,
    LevelEnum.ADVANCED: TierEnum.ADVANCED,
    LevelEnum.PRO: TierEnum.COMPETITIVE,
}


class OnboardingService:
    def __init__(
        self,
        users_repo: UsersRepo,
        tier_config_repo: TierConfigRepo,
        league_service: LeagueService | None = None,
    ) -> None:
        self.users_repo = users_repo
        self.tier_config_repo = tier_config_repo
        self.league_service = league_service

    def register_me(
        self,
        uid: str,
        token_email: str | None,
        token_picture: str | None,
        request: RegisterMeRequest,
    ) -> PrivateUserProfile:
        # 1. Resolve email
        email = token_email or request.email
        if not email:
            raise ValueError("email_required")

        # 2. Build per-sport rankings (camelCase for Firestore)
        try:
            tier_config = self.tier_config_repo.get()
        except ValueError as exc:
            raise OnboardingConfigError(str(exc)) from exc

        rankings: dict = {}
        for sport in request.sports:
            level = getattr(request.levels, sport.value)
            reg_tier = LEVEL_TO_TIER[level]
            try:
                pts = tier_config.get_floor(reg_tier)
            except ValueError as exc:
                raise OnboardingConfigError(str(exc)) from exc
            rankings[sport.value] = {
                "sport": sport.value,
                "pts": pts,
                "tier": reg_tier.value,
                "registrationTier": reg_tier.value,
                "currentStreak": 0,
                "bestStreak": 0,
                "globalRanking": None,
                "lastUpdated": None,
                "personalBest": None,
            }

        # 3. Build levels map (only declared sports)
        levels_map: dict = {
            sport.value: getattr(request.levels, sport.value).value for sport in request.sports
        }

        # 4. Build full Firestore document (camelCase — mappers expect this)
        now = datetime.now(timezone.utc)
        doc: dict = {
            "uid": uid,
            "name": request.name,
            "nameLower": request.name.strip().lower(),
            "email": str(email),
            "emailLower": normalize_email(str(email)),
            "profileUrl": str(request.profile_url) if request.profile_url else token_picture,
            "isPro": False,
            "phone": None,
            "rankings": rankings,
            "preferences": {
                "area": request.area,
                "levels": levels_map,
                "sports": [s.value for s in request.sports],
                "feedOptOut": False,
            },
            "leaguesActive": [],
            "leaguesCompleted": [],
            "upcomingMatches": [],
            "completedMatches": [],
            "journalRecent": [],
            "cursors": None,
            "northStarGoal": None,
            "skillDna": {},
            "deviceTokens": [],
            "playTab": {
                "state": "DISCOVERY",
                "activeBroadcastId": None,
                "activeMatchId": None,
                "activeOutgoingOfferId": None,
                "pendingIncomingOfferIds": [],
                "updatedAt": now,
            },
        }

        # 5. Persist and return
        self.users_repo.create_profile(uid, doc)

        # 6. Backfill any outstanding doubles partner invites addressed to this
        # email (consume-and-delete). Never fail registration if this errors.
        if self.league_service is not None:
            try:
                self.league_service.claim_partner_invites(uid, str(email))
            except Exception:
                logger.exception("claim_partner_invites failed during registration (non-fatal)")

        profile = self.users_repo.get_private_profile(uid)
        assert profile is not None
        return profile
