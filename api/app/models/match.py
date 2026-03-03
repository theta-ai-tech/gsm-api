from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.common import MatchScore
from app.models.enums import MatchResultEnum, MatchStatusEnum, ParticipantRoleEnum, SportEnum


class VerifyScoreRequest(GsmBaseModel):
    winner_uid: str
    score: MatchScore | None = None
    walkover: bool = False


class VerifyScoreResponse(GsmBaseModel):
    match_id: str
    status: MatchStatusEnum
    winner_uid: str
    loser_uid: str
    winner_delta: int
    loser_delta: int
    winner_new_pts: int
    loser_new_pts: int


class MatchParticipant(GsmBaseModel):
    uid: str
    team: int | None = None  # team number for doubles; None for singles
    role: ParticipantRoleEnum
    result: MatchResultEnum | None = None


class Match(GsmBaseModel):
    """
    participant_uids is a flattened list for fast Firestore-style queries (array-contains).
    score holds canonical structured scoring data.
    """

    match_id: str
    sport: SportEnum
    status: MatchStatusEnum
    scheduled_at: datetime | None = None
    finished_at: datetime | None = None
    league_id: str | None = None
    court_id: str | None = None
    score: MatchScore | None = None
    result_by_user: dict[str, MatchResultEnum] | None = None
    participants: list[MatchParticipant] = []
    participant_uids: list[str] = []
