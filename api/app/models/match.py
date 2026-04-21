from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.common import MatchScore, VenueRef
from app.models.enums import (
    MatchResultEnum,
    MatchStatusEnum,
    ParticipantRoleEnum,
    SportEnum,
    TierEnum,
)


class VerifyScoreRequest(GsmBaseModel):
    winner_uid: str
    score: MatchScore | None = None
    walkover: bool = False


class ScoringBreakdown(GsmBaseModel):
    base_win: int
    upset_bonus: int
    elo_bonus: int
    penalty: int


class ScoringPayload(GsmBaseModel):
    sport: SportEnum
    your_pts_before: int
    your_pts_after: int
    delta: int
    breakdown: ScoringBreakdown
    tier_before: TierEnum
    tier_after: TierEnum
    tier_crossed: bool


class VerifyScoreResponse(GsmBaseModel):
    match_id: str
    status: MatchStatusEnum
    winner_uid: str
    loser_uid: str
    winner_delta: int
    loser_delta: int
    winner_new_pts: int
    loser_new_pts: int
    scoring: ScoringPayload | None = None


class MatchParticipant(GsmBaseModel):
    uid: str
    team: int | None = None  # team number for doubles; None for singles
    role: ParticipantRoleEnum
    result: MatchResultEnum | None = None


def compute_participant_pair(uids: list[str]) -> str | None:
    """Return a deterministic pair key from two UIDs, sorted lexicographically."""
    if len(uids) != 2:
        return None
    return "_".join(sorted(uids))


class Match(GsmBaseModel):
    """
    participant_uids is a flattened list for fast Firestore-style queries (array-contains).
    participant_pair is a deterministic "uid_a_uid_b" string (sorted) for head-to-head queries.
    score holds canonical structured scoring data.
    """

    match_id: str
    sport: SportEnum
    status: MatchStatusEnum
    scheduled_at: datetime | None = None
    finished_at: datetime | None = None
    league_id: str | None = None
    court_id: str | None = None
    venue_ref: VenueRef | None = None
    score: MatchScore | None = None
    result_by_user: dict[str, MatchResultEnum] | None = None
    participants: list[MatchParticipant] = []
    participant_uids: list[str] = []
    participant_pair: str | None = None
