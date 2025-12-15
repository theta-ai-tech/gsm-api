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
