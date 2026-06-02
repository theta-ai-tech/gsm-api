from datetime import datetime, timezone

from app.models.enums import LevelEnum, TierEnum
from app.models.onboarding import RegisterMeRequest
from app.models.user import PrivateUserProfile
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo

LEVEL_TO_TIER: dict[LevelEnum, TierEnum] = {
    LevelEnum.BEGINNER: TierEnum.AMATEUR,
    LevelEnum.INTERMEDIATE: TierEnum.INTERMEDIATE,
    LevelEnum.ADVANCED: TierEnum.ADVANCED,
    LevelEnum.PRO: TierEnum.COMPETITIVE,
}


class OnboardingService:
    def __init__(self, users_repo: UsersRepo, tier_config_repo: TierConfigRepo) -> None:
        self.users_repo = users_repo
        self.tier_config_repo = tier_config_repo

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
        tier_config = self.tier_config_repo.get()
        rankings: dict = {}
        for sport in request.sports:
            level = getattr(request.levels, sport.value)
            reg_tier = LEVEL_TO_TIER[level]
            pts = tier_config.get_floor(reg_tier)
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
            "email": str(email),
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
        profile = self.users_repo.get_private_profile(uid)
        assert profile is not None
        return profile
