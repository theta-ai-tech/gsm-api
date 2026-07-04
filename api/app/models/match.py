from datetime import datetime

from pydantic import model_validator

from app.models.base import GsmBaseModel
from app.models.common import MatchScore, VenueRef
from app.models.enums import (
    MatchResultEnum,
    MatchStatusEnum,
    MatchTypeEnum,
    ParticipantRoleEnum,
    SportEnum,
    TierEnum,
)


class VerifyScoreRequest(GsmBaseModel):
    """Score-submission payload for ``POST /matches/{id}/verify-score``.

    For singles matches the caller must supply ``winner_uid`` (legacy shape).
    For doubles matches (DBL-5) the caller supplies ``winner_team`` instead —
    ``'A'`` or ``'B'`` — since the winning side has 2 UIDs. Exactly one of
    the two fields must be set; the service layer enforces that the value
    matches the underlying match type.
    """

    winner_uid: str | None = None
    winner_team: str | None = None
    score: MatchScore | None = None
    walkover: bool = False

    @model_validator(mode="after")
    def _validate_winner_target(self) -> "VerifyScoreRequest":
        if self.winner_uid is None and self.winner_team is None:
            msg = "exactly one of winner_uid or winner_team must be provided"
            raise ValueError(msg)
        if self.winner_uid is not None and self.winner_team is not None:
            msg = "provide either winner_uid (singles) or winner_team (doubles), not both"
            raise ValueError(msg)
        if self.winner_team is not None and self.winner_team not in {"A", "B"}:
            msg = "winner_team must be 'A' or 'B'"
            raise ValueError(msg)
        return self


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
    """Response for ``POST /matches/{id}/verify-score``.

    For doubles (DBL-5), ``winner_uid`` / ``loser_uid`` are empty strings and
    ``winner_team`` / ``loser_team`` carry the side labels instead. Singles
    responses keep the legacy shape (winner_uid / loser_uid populated,
    winner_team / loser_team None).
    """

    match_id: str
    status: MatchStatusEnum
    winner_uid: str = ""
    loser_uid: str = ""
    winner_team: str | None = None
    loser_team: str | None = None
    winner_delta: int = 0
    loser_delta: int = 0
    winner_new_pts: int = 0
    loser_new_pts: int = 0
    scoring: ScoringPayload | None = None


class MatchParticipant(GsmBaseModel):
    """A participant entry on a match document.

    Aligned with :class:`ParticipantEntry` from DBL-1: ``team`` is ``'A'`` or
    ``'B'`` for doubles and ``None`` for singles. ``display_name`` is optional
    here because matches written before DBL-2 do not carry the cached label.
    """

    uid: str
    team: str | None = None  # 'A' or 'B' for doubles; None for singles
    role: ParticipantRoleEnum
    result: MatchResultEnum | None = None
    display_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_team(cls, data: object) -> object:
        """Coerce legacy integer ``team`` values (1/2) to ``'A'``/``'B'``.

        Pre-DBL-2 documents stored ``team: 1`` / ``team: 2``; the on-read
        coercion keeps those documents parseable without a backfill.
        """
        if isinstance(data, dict):
            data = dict(data)
            team_val = data.get("team")
            if isinstance(team_val, int):
                if team_val == 1:
                    data["team"] = "A"
                elif team_val == 2:
                    data["team"] = "B"
        return data

    @model_validator(mode="after")
    def _validate_team(self) -> "MatchParticipant":
        if self.team is not None and self.team not in {"A", "B"}:
            msg = "team must be 'A', 'B', or None"
            raise ValueError(msg)
        return self


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
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    scheduled_at: datetime | None = None
    finished_at: datetime | None = None
    league_id: str | None = None
    division_id: str | None = None
    court_id: str | None = None
    venue_ref: VenueRef | None = None
    score: MatchScore | None = None
    result_by_user: dict[str, MatchResultEnum] | None = None
    participants: list[MatchParticipant] = []
    participant_uids: list[str] = []
    participant_pair: str | None = None
    result_submitted_by: list[str] = []

    @model_validator(mode="after")
    def _validate_participants_for_match_type(self) -> "Match":
        """Enforce singles/doubles participant rules.

        Validation only fires when ``participants`` is non-empty so that
        legacy/test code that constructs a ``Match`` without the participants
        array (relying on ``participant_uids`` only) keeps working. The
        on-read mapper backfills ``participants`` from ``participant_uids``
        for legacy Firestore documents, so all real reads still flow through
        validation.
        """
        if not self.participants:
            return self

        if self.match_type == MatchTypeEnum.SINGLES:
            if len(self.participants) != 2:
                msg = "singles match must have exactly 2 participants"
                raise ValueError(msg)
            if any(p.team is not None for p in self.participants):
                msg = "singles participants must have team=None"
                raise ValueError(msg)
            return self

        # Doubles
        if len(self.participants) != 4:
            msg = "doubles match must have exactly 4 participants"
            raise ValueError(msg)
        teams = [p.team for p in self.participants]
        if any(t not in {"A", "B"} for t in teams):
            msg = "doubles participants must each have team set to 'A' or 'B'"
            raise ValueError(msg)
        if teams.count("A") != 2 or teams.count("B") != 2:
            msg = "doubles must have exactly 2 participants per team"
            raise ValueError(msg)
        return self
