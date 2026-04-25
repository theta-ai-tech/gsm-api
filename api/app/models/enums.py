from enum import StrEnum


class SportEnum(StrEnum):
    TENNIS = "tennis"
    PADEL = "padel"
    PICKLEBALL = "pickleball"


class LevelEnum(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    PRO = "pro"


class MatchStatusEnum(StrEnum):
    SCHEDULED = "scheduled"
    PENDING_CONFIRMATION = "pending_confirmation"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"


class MatchTypeEnum(StrEnum):
    SINGLES = "singles"
    DOUBLES = "doubles"


class BroadcastTypeEnum(StrEnum):
    FIND_OPPONENT = "find_opponent"
    FIND_FOURTH = "find_fourth"


class LeagueStatusEnum(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    UPCOMING = "upcoming"


class LeagueRoleEnum(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"
    CAPTAIN = "captain"


class LeagueMemberStatusEnum(StrEnum):
    ACTIVE = "active"
    LEFT = "left"
    BANNED = "banned"


class ParticipantRoleEnum(StrEnum):
    PLAYER = "player"
    REFEREE = "referee"


class MatchResultEnum(StrEnum):
    WIN = "W"
    LOSS = "L"
    DRAW = "D"


class JournalVisibilityEnum(StrEnum):
    PRIVATE = "private"
    FRIENDS = "friends"


class PlayTabStateEnum(StrEnum):
    DISCOVERY = "DISCOVERY"
    BROADCAST_ACTIVE = "BROADCAST_ACTIVE"
    OUTGOING_OFFER_PENDING = "OUTGOING_OFFER_PENDING"
    INCOMING_OFFER_PENDING = "INCOMING_OFFER_PENDING"
    MATCH_SCHEDULED = "MATCH_SCHEDULED"
    POST_MATCH_LOG_AVAILABLE = "POST_MATCH_LOG_AVAILABLE"
    POST_MATCH_WAITING_OPPONENT = "POST_MATCH_WAITING_OPPONENT"
    POST_MATCH_CONFIRM_REQUIRED = "POST_MATCH_CONFIRM_REQUIRED"
    MATCH_DISPUTED = "MATCH_DISPUTED"


class BroadcastStatusEnum(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    MATCHED = "matched"


class AvailabilityEnum(StrEnum):
    TODAY = "today"
    TOMORROW = "tomorrow"
    WEEKEND = "weekend"


class CourtStatusEnum(StrEnum):
    HAVE_COURT = "have_court"
    NEED_COURT = "need_court"


class OfferStatusEnum(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class JournalEntryTypeEnum(StrEnum):
    MATCH = "match"
    TRAINING = "training"


class TrainingFocusEnum(StrEnum):
    SERVE = "serve"
    VOLLEY = "volley"
    FOOTWORK = "footwork"
    BACKHAND = "backhand"
    CARDIO = "cardio"
    STRATEGY = "strategy"


class TierEnum(StrEnum):
    AMATEUR = "amateur"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    COMPETITIVE = "competitive"


class TickerEventTypeEnum(StrEnum):
    UPSET = "upset"
    PERSONAL_BEST = "personal_best"
    WIN_STREAK = "win_streak"
    TIER_CROSSED = "tier_crossed"


class PointHistoryReasonEnum(StrEnum):
    MATCH_WIN = "match_win"
    MATCH_LOSS = "match_loss"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    TIER_REBALANCE = "tier_rebalance"
