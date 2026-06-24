from datetime import datetime

from pydantic import Field, HttpUrl, model_validator

from app.models.base import GsmBaseModel
from app.models.common import MatchScore, SportRanking, VenueRef
from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    LevelEnum,
    MatchTypeEnum,
    OfferStatusEnum,
    ParticipantRoleEnum,
    PlayTabStateEnum,
    SportEnum,
)


class GeoLocation(GsmBaseModel):
    lat: float
    lng: float


class BroadcastLocation(GsmBaseModel):
    area: int | None = None
    geo: GeoLocation | None = None
    radius_km: float | None = None


def _validate_doubles_fields(
    match_type: MatchTypeEnum,
    broadcast_type: BroadcastTypeEnum,
    partner_uid: str | None,
) -> None:
    """Shared validation for the (matchType, broadcastType, partnerUid) trio.

    Rules (DBL-3):
    - ``find_fourth`` requires ``match_type=doubles`` (a singles broadcast can't
      look for a 4th).
    - ``doubles`` + ``find_opponent`` requires a ``partner_uid`` (you challenge
      as a team, so we need the partner up front).
    - ``doubles`` + ``find_fourth`` makes ``partner_uid`` optional (caller may
      be solo looking for 3 others or a pair looking for 1 more).
    - ``singles`` + ``find_opponent`` ignores ``partner_uid`` if supplied.
    """
    if broadcast_type == BroadcastTypeEnum.FIND_FOURTH:
        if match_type != MatchTypeEnum.DOUBLES:
            msg = "broadcast_type=find_fourth requires match_type=doubles"
            raise ValueError(msg)

    if (
        match_type == MatchTypeEnum.DOUBLES
        and broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
        and not partner_uid
    ):
        msg = "match_type=doubles + broadcast_type=find_opponent requires partner_uid"
        raise ValueError(msg)


class Broadcast(GsmBaseModel):
    broadcast_id: str
    owner_uid: str
    owner_name: str
    owner_ranking: SportRanking | None = None
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT
    partner_uid: str | None = None
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    venue_ref: VenueRef | None = None
    status: BroadcastStatusEnum
    expires_at: datetime
    created_at: datetime
    location: BroadcastLocation

    @model_validator(mode="after")
    def _validate_doubles(self) -> "Broadcast":
        _validate_doubles_fields(self.match_type, self.broadcast_type, self.partner_uid)
        return self


class Offer(GsmBaseModel):
    offer_id: str
    from_uid: str
    from_name: str
    from_ranking: SportRanking | None = None
    to_uid: str
    to_name: str
    to_ranking: SportRanking | None = None
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    partner_uid: str | None = None
    proposed_time: datetime
    court_location: str | None = None
    venue_ref: VenueRef | None = None
    source_broadcast_id: str | None = None
    league_id: str | None = None
    message: str | None = None
    status: OfferStatusEnum
    expires_at: datetime
    created_at: datetime
    match_id: str | None = None

    @model_validator(mode="after")
    def _validate_doubles(self) -> "Offer":
        # Doubles offers must carry a partner. Singles offers must not.
        if self.match_type == MatchTypeEnum.DOUBLES and not self.partner_uid:
            msg = "match_type=doubles requires partner_uid on the offer"
            raise ValueError(msg)
        if self.match_type == MatchTypeEnum.SINGLES and self.partner_uid:
            msg = "match_type=singles offer must not carry a partner_uid"
            raise ValueError(msg)
        return self


class CreateBroadcastRequest(GsmBaseModel):
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT
    partner_uid: str | None = None
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    venue_ref: VenueRef | None = None
    expires_at: datetime
    location: BroadcastLocation

    @model_validator(mode="after")
    def _validate_doubles(self) -> "CreateBroadcastRequest":
        _validate_doubles_fields(self.match_type, self.broadcast_type, self.partner_uid)
        return self


class CreateBroadcastResponse(GsmBaseModel):
    broadcast_id: str
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT
    partner_uid: str | None = None
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    status: BroadcastStatusEnum
    expires_at: datetime
    created_at: datetime


class SendOfferRequest(GsmBaseModel):
    to_uid: str
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    partner_uid: str | None = None
    proposed_time: datetime
    court_location: str | None = None
    venue_ref: VenueRef | None = None
    source_broadcast_id: str | None = None
    message: str | None = None
    league_id: str | None = None

    @model_validator(mode="after")
    def _validate_doubles(self) -> "SendOfferRequest":
        # Doubles offers always require a partner_uid (you challenge as a team
        # against a doubles broadcast). Singles offers must not carry one.
        if self.match_type == MatchTypeEnum.DOUBLES and not self.partner_uid:
            msg = "match_type=doubles requires partner_uid"
            raise ValueError(msg)
        if self.match_type == MatchTypeEnum.SINGLES and self.partner_uid:
            msg = "match_type=singles offer must not include partner_uid"
            raise ValueError(msg)
        return self


class SendOfferResponse(GsmBaseModel):
    offer_id: str
    to_uid: str
    to_name: str
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    partner_uid: str | None = None
    proposed_time: datetime
    status: OfferStatusEnum
    expires_at: datetime
    created_at: datetime


class OfferActionResponse(GsmBaseModel):
    offer_id: str
    status: OfferStatusEnum
    match_id: str | None = None
    scheduled_at: datetime | None = None


class PendingOfferSummary(GsmBaseModel):
    offer_id: str
    from_uid: str
    from_name: str
    from_ranking: SportRanking | None = None
    proposed_time: datetime
    message: str | None = None
    expires_at: datetime
    created_at: datetime


class OpponentSummary(GsmBaseModel):
    uid: str
    name: str
    profile_url: HttpUrl | None = None
    ranking: SportRanking | None = None


class MeStateParticipant(GsmBaseModel):
    """Participant entry surfaced in /me/state payloads.

    Mirrors ``MatchParticipant`` from the match document but always carries a
    resolved display name so the mobile client can render Team A vs Team B
    labels without an extra users lookup. ``team`` is ``'A'`` / ``'B'`` for
    doubles and ``None`` for singles (DBL-7).
    """

    uid: str
    name: str = ""
    team: str | None = None
    role: ParticipantRoleEnum = ParticipantRoleEnum.PLAYER


class MeStatePrimary(GsmBaseModel):
    broadcast_id: str | None = None
    match_id: str | None = None
    active_offer_ids: list[str] = []


class BroadcastActivePayload(GsmBaseModel):
    broadcast_id: str
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT
    partner_uid: str | None = None
    partner_name: str | None = None
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    venue_ref: VenueRef | None = None
    expires_at: datetime
    created_at: datetime
    pending_offers: list[PendingOfferSummary] = []


class OutgoingOfferPayload(GsmBaseModel):
    offer_id: str
    to_uid: str
    to_name: str
    to_ranking: SportRanking | None = None
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    partner_uid: str | None = None
    partner_name: str | None = None
    proposed_time: datetime
    court_location: str | None = None
    message: str | None = None
    expires_at: datetime
    created_at: datetime


class IncomingOfferPayload(GsmBaseModel):
    offer_id: str
    from_uid: str
    from_name: str
    from_ranking: SportRanking | None = None
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    partner_uid: str | None = None
    partner_name: str | None = None
    proposed_time: datetime
    court_location: str | None = None
    message: str | None = None
    expires_at: datetime
    created_at: datetime


class MatchScheduledPayload(GsmBaseModel):
    match_id: str
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    scheduled_at: datetime
    court_id: str | None = None
    court_name: str | None = None
    court_geo: GeoLocation | None = None
    venue_ref: VenueRef | None = None
    opponent: OpponentSummary
    participants: list[MeStateParticipant] = []


class PostMatchLogAvailablePayload(GsmBaseModel):
    match_id: str
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    scheduled_at: datetime
    opponent: OpponentSummary
    participants: list[MeStateParticipant] = []


class PostMatchWaitingOpponentPayload(GsmBaseModel):
    match_id: str
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    submitted_score: MatchScore
    opponent: OpponentSummary
    participants: list[MeStateParticipant] = []


class PostMatchConfirmRequiredPayload(GsmBaseModel):
    match_id: str
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    opponent_score: MatchScore
    opponent: OpponentSummary
    participants: list[MeStateParticipant] = []


class MatchDisputedPayload(GsmBaseModel):
    match_id: str
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    my_score: MatchScore
    opponent_score: MatchScore
    opponent: OpponentSummary
    participants: list[MeStateParticipant] = []


class UIEvent(GsmBaseModel):
    type: str
    message: str
    meta: dict[str, str] | None = None


class DiscoveryBroadcastCard(GsmBaseModel):
    """A single card shown in the DISCOVERY feed."""

    broadcast_id: str
    owner_uid: str
    owner_name: str
    owner_ranking: SportRanking | None = None
    sport: SportEnum
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    expires_at: datetime
    created_at: datetime


class DiscoveryAnnotations(GsmBaseModel):
    """Aggregate counts surfaced alongside the discovery feed."""

    nearby_count: int
    doubles_count: int
    find_fourth_count: int


class DiscoveryPayload(GsmBaseModel):
    """Payload returned when mode == DISCOVERY."""

    broadcasts: list[DiscoveryBroadcastCard] = []


class DiscoveryFeedItem(GsmBaseModel):
    """One browsable intent in the GET /me/discovery feed."""

    to_uid: str = Field(alias="toUid")
    name: str
    ranking: SportRanking | None = None
    level: LevelEnum | None = None
    sport: SportEnum
    match_type: MatchTypeEnum = Field(default=MatchTypeEnum.SINGLES, alias="matchType")
    broadcast_type: BroadcastTypeEnum = Field(
        default=BroadcastTypeEnum.FIND_OPPONENT, alias="broadcastType"
    )
    availability: AvailabilityEnum
    court_status: CourtStatusEnum = Field(alias="courtStatus")
    venue_ref: VenueRef | None = Field(default=None, alias="venueRef")
    area_name: str | None = Field(default=None, alias="areaName")
    expires_at: datetime = Field(alias="expiresAt")
    created_at: datetime = Field(alias="createdAt")
    broadcast_id: str = Field(alias="broadcastId")


class DiscoveryFeedResponse(GsmBaseModel):
    """Response shape for GET /me/discovery."""

    server_time: datetime = Field(alias="serverTime")
    active_clubs_nearby: int = Field(alias="activeClubsNearby")
    intents: list[DiscoveryFeedItem] = []


class MeStateResponse(GsmBaseModel):
    mode: PlayTabStateEnum
    server_time: datetime
    primary: MeStatePrimary
    payload: (
        dict
        | BroadcastActivePayload
        | OutgoingOfferPayload
        | IncomingOfferPayload
        | MatchScheduledPayload
        | PostMatchLogAvailablePayload
        | PostMatchWaitingOpponentPayload
        | PostMatchConfirmRequiredPayload
        | MatchDisputedPayload
        | DiscoveryPayload
    ) = {}
    annotations: dict | DiscoveryAnnotations = {}
    ui_events: list[UIEvent] = []
