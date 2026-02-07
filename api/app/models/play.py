from datetime import datetime

from pydantic import HttpUrl

from app.models.base import GsmBaseModel
from app.models.common import MatchScore, SportRanking
from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    CourtStatusEnum,
    OfferStatusEnum,
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


class Broadcast(GsmBaseModel):
    broadcast_id: str
    owner_uid: str
    owner_name: str
    owner_ranking: SportRanking | None = None
    sport: SportEnum
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    status: BroadcastStatusEnum
    expires_at: datetime
    created_at: datetime
    location: BroadcastLocation


class Offer(GsmBaseModel):
    offer_id: str
    from_uid: str
    from_name: str
    from_ranking: SportRanking | None = None
    to_uid: str
    to_name: str
    to_ranking: SportRanking | None = None
    sport: SportEnum
    proposed_time: datetime
    court_location: str | None = None
    message: str | None = None
    status: OfferStatusEnum
    expires_at: datetime
    created_at: datetime
    match_id: str | None = None


class CreateBroadcastRequest(GsmBaseModel):
    sport: SportEnum
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    expires_at: datetime
    location: BroadcastLocation


class CreateBroadcastResponse(GsmBaseModel):
    broadcast_id: str
    sport: SportEnum
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    status: BroadcastStatusEnum
    expires_at: datetime
    created_at: datetime


class SendOfferRequest(GsmBaseModel):
    to_uid: str
    sport: SportEnum
    proposed_time: datetime
    court_location: str | None = None
    message: str | None = None


class SendOfferResponse(GsmBaseModel):
    offer_id: str
    to_uid: str
    to_name: str
    sport: SportEnum
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


class MeStatePrimary(GsmBaseModel):
    broadcast_id: str | None = None
    match_id: str | None = None
    active_offer_ids: list[str] = []


class BroadcastActivePayload(GsmBaseModel):
    broadcast_id: str
    sport: SportEnum
    availability: AvailabilityEnum
    court_status: CourtStatusEnum
    court_location: str | None = None
    expires_at: datetime
    created_at: datetime
    pending_offers: list[PendingOfferSummary] = []


class OutgoingOfferPayload(GsmBaseModel):
    offer_id: str
    to_uid: str
    to_name: str
    to_ranking: SportRanking | None = None
    sport: SportEnum
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
    proposed_time: datetime
    court_location: str | None = None
    message: str | None = None
    expires_at: datetime
    created_at: datetime


class MatchScheduledPayload(GsmBaseModel):
    match_id: str
    sport: SportEnum
    scheduled_at: datetime
    court_id: str | None = None
    court_name: str | None = None
    court_geo: GeoLocation | None = None
    opponent: OpponentSummary


class PostMatchLogAvailablePayload(GsmBaseModel):
    match_id: str
    sport: SportEnum
    scheduled_at: datetime
    opponent: OpponentSummary


class PostMatchWaitingOpponentPayload(GsmBaseModel):
    match_id: str
    submitted_score: MatchScore
    opponent: OpponentSummary


class PostMatchConfirmRequiredPayload(GsmBaseModel):
    match_id: str
    opponent_score: MatchScore
    opponent: OpponentSummary


class MatchDisputedPayload(GsmBaseModel):
    match_id: str
    my_score: MatchScore
    opponent_score: MatchScore
    opponent: OpponentSummary


class UIEvent(GsmBaseModel):
    type: str
    message: str
    meta: dict[str, str] | None = None


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
    ) = {}
    annotations: dict = {}
    ui_events: list[UIEvent] = []
