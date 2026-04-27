"""
PlayService - Business logic for Tab 1 PLAY matchmaking.

Handles:
- State computation and freshness reconciliation
- Transactional writes for state transitions
- Broadcast/offer/match lifecycle management
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import (
    BroadcastStatusEnum,
    CourtStatusEnum,
    MatchStatusEnum,
    MatchTypeEnum,
    OfferStatusEnum,
    ParticipantRoleEnum,
    PlayTabStateEnum,
)
from app.models import compute_participant_pair
from app.models.play import (
    BroadcastActivePayload,
    CreateBroadcastRequest,
    CreateBroadcastResponse,
    IncomingOfferPayload,
    MatchScheduledPayload,
    MeStatePrimary,
    MeStateResponse,
    OpponentSummary,
    OfferActionResponse,
    OutgoingOfferPayload,
    PendingOfferSummary,
    SendOfferRequest,
    SendOfferResponse,
)
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.mappers import _parse_sport_ranking
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo

logger = logging.getLogger(__name__)


def _short_display_name(full_name: str) -> str:
    """Format ``Firstname Lastname`` as ``Firstname L.`` for cached display.

    Mirrors the shape that DBL-1's ``ParticipantEntry.display_name`` expects
    (short label for UI). Falls back to the raw name when there is no
    last-name token, and to an empty string for falsy input — callers should
    pass a non-empty name for new matches.
    """
    parts = (full_name or "").strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return parts[0] if parts else ""


class PlayService:
    """Service for Tab 1 PLAY business logic."""

    def __init__(
        self,
        users_repo: UsersRepo,
        broadcasts_repo: BroadcastsRepo,
        matches_repo: MatchesRepo,
        offers_repo: OffersRepo,
        firestore_client: firestore.Client,
    ):
        self.users_repo = users_repo
        self.broadcasts_repo = broadcasts_repo
        self.matches_repo = matches_repo
        self.offers_repo = offers_repo
        self.client = firestore_client

    # ===== GET /me/state =====

    def get_me_state(self, uid: str) -> MeStateResponse:
        """
        Get current Tab 1 state for a user with freshness reconciliation.

        Reads persisted playTab from user doc, checks for time-based expirations,
        corrects stale state if needed, and returns mode-specific payload.
        """
        user_doc = self.users_repo.get_user_doc(uid)
        if not user_doc:
            # User doesn't exist - return DISCOVERY
            return MeStateResponse(
                mode=PlayTabStateEnum.DISCOVERY,
                server_time=datetime.now(timezone.utc),
                primary=MeStatePrimary(),
                payload={},
            )

        play_tab = user_doc.get("playTab", {}) or {}
        state = play_tab.get("state", "DISCOVERY")
        now = datetime.now(timezone.utc)

        # Freshness reconciliation
        corrected_state, ui_events = self._reconcile_freshness(uid, state, play_tab, now)

        if corrected_state != state:
            # State was stale - update user doc
            self.users_repo.update_play_tab(uid, {"state": corrected_state, "updatedAt": now})
            state = corrected_state

        # Build response based on final state
        return self._build_state_response(uid, state, play_tab, now, ui_events)

    def _reconcile_freshness(
        self, uid: str, state: str, play_tab: dict, now: datetime
    ) -> tuple[str, list]:
        """
        Check for time-based state corrections.

        Returns:
            (corrected_state, ui_events)
        """
        ui_events = []

        if state == "BROADCAST_ACTIVE":
            broadcast_id = play_tab.get("activeBroadcastId")
            if broadcast_id:
                broadcast = self.broadcasts_repo.get_by_id(broadcast_id)
                if broadcast and broadcast.expires_at < now:
                    # Broadcast expired
                    self.broadcasts_repo.update_status(broadcast_id, BroadcastStatusEnum.EXPIRED)
                    ui_events.append(
                        {"type": "broadcast_expired", "message": "Your broadcast has expired."}
                    )
                    return "DISCOVERY", ui_events

        elif state == "OUTGOING_OFFER_PENDING":
            offer_id = play_tab.get("activeOutgoingOfferId")
            if offer_id:
                offer = self.offers_repo.get_by_id(offer_id)
                if offer and offer.expires_at < now:
                    # Offer expired
                    self.offers_repo.update_status(offer_id, OfferStatusEnum.EXPIRED)
                    ui_events.append(
                        {"type": "offer_expired", "message": "Your offer has expired."}
                    )
                    # Check if user still has active broadcast
                    broadcast_id = play_tab.get("activeBroadcastId")
                    if broadcast_id:
                        return "BROADCAST_ACTIVE", ui_events
                    return "DISCOVERY", ui_events

        elif state == "INCOMING_OFFER_PENDING":
            pending_ids = play_tab.get("pendingIncomingOfferIds", [])
            if pending_ids:
                # Check if the single pending offer expired
                offer = self.offers_repo.get_by_id(pending_ids[0])
                if offer and offer.expires_at < now:
                    self.offers_repo.update_status(pending_ids[0], OfferStatusEnum.EXPIRED)
                    ui_events.append({"type": "offer_expired", "message": "Offer has expired."})
                    return "DISCOVERY", ui_events

        elif state == "MATCH_SCHEDULED":
            match_id = play_tab.get("activeMatchId")
            if match_id:
                # Check if match time has passed
                # TODO: Fetch match doc and check scheduledAt
                # For now, skip this transition (will be E16+)
                pass

        return state, ui_events

    def _build_state_response(
        self, uid: str, state: str, play_tab: dict, now: datetime, ui_events: list
    ) -> MeStateResponse:
        """Build the MeStateResponse based on current state."""
        mode = PlayTabStateEnum(state)

        primary = MeStatePrimary(
            broadcast_id=play_tab.get("activeBroadcastId"),
            match_id=play_tab.get("activeMatchId"),
            active_offer_ids=play_tab.get("pendingIncomingOfferIds", [])
            + (
                [play_tab.get("activeOutgoingOfferId")]
                if play_tab.get("activeOutgoingOfferId")
                else []
            ),
        )

        payload: dict = {}

        if mode == PlayTabStateEnum.BROADCAST_ACTIVE:
            broadcast_id = play_tab.get("activeBroadcastId")
            if broadcast_id:
                broadcast = self.broadcasts_repo.get_by_id(broadcast_id)
                if broadcast:
                    pending_offer_ids = play_tab.get("pendingIncomingOfferIds", [])
                    pending_offers = self.offers_repo.get_by_ids(pending_offer_ids)
                    payload = BroadcastActivePayload(
                        broadcast_id=broadcast.broadcast_id,
                        sport=broadcast.sport,
                        match_type=broadcast.match_type,
                        broadcast_type=broadcast.broadcast_type,
                        partner_uid=broadcast.partner_uid,
                        availability=broadcast.availability,
                        court_status=broadcast.court_status,
                        court_location=broadcast.court_location,
                        venue_ref=broadcast.venue_ref,
                        expires_at=broadcast.expires_at,
                        created_at=broadcast.created_at,
                        pending_offers=[
                            PendingOfferSummary(
                                offer_id=o.offer_id,
                                from_uid=o.from_uid,
                                from_name=o.from_name,
                                from_ranking=o.from_ranking,
                                proposed_time=o.proposed_time,
                                message=o.message,
                                expires_at=o.expires_at,
                                created_at=o.created_at,
                            )
                            for o in pending_offers
                        ],
                    ).model_dump(by_alias=True)

        elif mode == PlayTabStateEnum.OUTGOING_OFFER_PENDING:
            offer_id = play_tab.get("activeOutgoingOfferId")
            if offer_id:
                offer = self.offers_repo.get_by_id(offer_id)
                if offer:
                    payload = OutgoingOfferPayload(
                        offer_id=offer.offer_id,
                        to_uid=offer.to_uid,
                        to_name=offer.to_name,
                        to_ranking=offer.to_ranking,
                        sport=offer.sport,
                        proposed_time=offer.proposed_time,
                        court_location=offer.court_location,
                        message=offer.message,
                        expires_at=offer.expires_at,
                        created_at=offer.created_at,
                    ).model_dump(by_alias=True)

        elif mode == PlayTabStateEnum.INCOMING_OFFER_PENDING:
            pending_ids = play_tab.get("pendingIncomingOfferIds", [])
            if pending_ids:
                offer = self.offers_repo.get_by_id(pending_ids[0])
                if offer:
                    payload = IncomingOfferPayload(
                        offer_id=offer.offer_id,
                        from_uid=offer.from_uid,
                        from_name=offer.from_name,
                        from_ranking=offer.from_ranking,
                        sport=offer.sport,
                        proposed_time=offer.proposed_time,
                        court_location=offer.court_location,
                        message=offer.message,
                        expires_at=offer.expires_at,
                        created_at=offer.created_at,
                    ).model_dump(by_alias=True)

        elif mode == PlayTabStateEnum.MATCH_SCHEDULED:
            match_id = play_tab.get("activeMatchId")
            if match_id:
                match = self.matches_repo.get_by_id(match_id)
                if match and match.scheduled_at:
                    opponent = next(
                        (
                            participant
                            for participant in match.participants
                            if participant.uid != uid
                        ),
                        None,
                    )
                    opponent_doc = (
                        self.users_repo.get_user_doc(opponent.uid) if opponent else None
                    ) or {}
                    opponent_rankings = opponent_doc.get("rankings", {}) or {}
                    opponent_ranking = _parse_sport_ranking(
                        opponent_rankings.get(match.sport.value)
                    )
                    payload = MatchScheduledPayload(
                        match_id=match.match_id,
                        sport=match.sport,
                        scheduled_at=match.scheduled_at,
                        court_id=match.court_id,
                        venue_ref=match.venue_ref,
                        opponent=OpponentSummary(
                            uid=opponent.uid if opponent else "",
                            name=opponent_doc.get("name", ""),
                            profile_url=opponent_doc.get("profileUrl"),
                            ranking=opponent_ranking,
                        ),
                    ).model_dump(by_alias=True)

        return MeStateResponse(
            mode=mode,
            server_time=now,
            primary=primary,
            payload=payload,
            ui_events=ui_events,
        )

    # ===== POST /me/broadcast =====

    def create_broadcast(
        self, uid: str, request: CreateBroadcastRequest
    ) -> CreateBroadcastResponse:
        """
        Create an availability broadcast.

        Preconditions:
        - User must be in DISCOVERY state
        """
        user_doc = self.users_repo.get_user_doc(uid)
        if not user_doc:
            raise ValueError("User not found")

        play_tab = user_doc.get("playTab", {}) or {}
        state = play_tab.get("state", "DISCOVERY")

        if state != "DISCOVERY":
            raise ValueError(
                f"Cannot create broadcast: user is in {state} state, must be DISCOVERY"
            )

        now = datetime.now(timezone.utc)
        if request.expires_at <= now:
            raise ValueError("expiresAt must be in the future")

        venue_ref = request.venue_ref
        if request.court_status == CourtStatusEnum.NEED_COURT:
            venue_ref = None
        elif venue_ref is None:
            logger.warning(
                "Broadcast created without venueRef despite court_status=have_court uid=%s",
                uid,
            )

        # Get user profile for denormalized fields
        user_name = user_doc.get("name", "")
        rankings = user_doc.get("rankings", {}) or {}
        sport_ranking = rankings.get(request.sport.value)

        # Doubles fields (DBL-3). For singles, partner_uid is always None even
        # if the request supplied one — singles broadcasts have no partner.
        partner_uid = request.partner_uid
        if request.match_type == MatchTypeEnum.SINGLES:
            partner_uid = None

        # Build broadcast doc (camelCase for Firestore)
        broadcast_data = {
            "ownerUid": uid,
            "ownerName": user_name,
            "ownerRanking": sport_ranking,
            "sport": request.sport.value,
            "matchType": request.match_type.value,
            "broadcastType": request.broadcast_type.value,
            "partnerUid": partner_uid,
            "availability": request.availability.value,
            "courtStatus": request.court_status.value,
            "courtLocation": request.court_location,
            "venueRef": venue_ref.model_dump(by_alias=True) if venue_ref else None,
            "status": "active",
            "expiresAt": request.expires_at,
            "createdAt": now,
            "location": {
                "area": request.location.area,
                "geo": (
                    {"lat": request.location.geo.lat, "lng": request.location.geo.lng}
                    if request.location.geo
                    else None
                ),
                "radiusKm": request.location.radius_km,
            },
        }

        # Transactional write
        transaction = self.client.transaction()

        @firestore.transactional
        def create_broadcast_txn(txn):
            # Create broadcast
            broadcast_ref = self.client.collection("broadcasts").document()
            txn.set(broadcast_ref, broadcast_data)

            # Update user playTab
            user_ref = self.client.collection("users").document(uid)
            txn.update(
                user_ref,
                {
                    "playTab.state": "BROADCAST_ACTIVE",
                    "playTab.activeBroadcastId": broadcast_ref.id,
                    "playTab.updatedAt": now,
                },
            )
            return broadcast_ref.id

        broadcast_id = create_broadcast_txn(transaction)

        return CreateBroadcastResponse(
            broadcast_id=broadcast_id,
            sport=request.sport,
            match_type=request.match_type,
            broadcast_type=request.broadcast_type,
            partner_uid=partner_uid,
            availability=request.availability,
            court_status=request.court_status,
            court_location=request.court_location,
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=request.expires_at,
            created_at=now,
        )

    # ===== DELETE /me/broadcast =====

    def cancel_broadcast(self, uid: str) -> None:
        """
        Cancel the user's active broadcast.

        Preconditions:
        - User must be in BROADCAST_ACTIVE state
        """
        user_doc = self.users_repo.get_user_doc(uid)
        if not user_doc:
            raise ValueError("User not found")

        play_tab = user_doc.get("playTab", {}) or {}
        state = play_tab.get("state")
        broadcast_id = play_tab.get("activeBroadcastId")

        if state != "BROADCAST_ACTIVE" or not broadcast_id:
            raise ValueError("No active broadcast to cancel")

        pending_offer_ids = play_tab.get("pendingIncomingOfferIds", [])

        # Transactional write
        transaction = self.client.transaction()

        @firestore.transactional
        def cancel_broadcast_txn(txn):
            # Update broadcast status
            broadcast_ref = self.client.collection("broadcasts").document(broadcast_id)
            txn.update(broadcast_ref, {"status": "cancelled"})

            # Decline all pending offers
            for offer_id in pending_offer_ids:
                offer_ref = self.client.collection("offers").document(offer_id)
                txn.update(offer_ref, {"status": "declined"})

            # Update user playTab
            user_ref = self.client.collection("users").document(uid)
            txn.update(
                user_ref,
                {
                    "playTab.state": "DISCOVERY",
                    "playTab.activeBroadcastId": None,
                    "playTab.pendingIncomingOfferIds": [],
                    "playTab.updatedAt": datetime.now(timezone.utc),
                },
            )

        cancel_broadcast_txn(transaction)

    # ===== POST /me/offers =====

    def send_offer(self, from_uid: str, request: SendOfferRequest) -> SendOfferResponse:
        """
        Send a challenge offer to another user.

        Preconditions:
        - Sender must be in DISCOVERY or BROADCAST_ACTIVE
        - Sender must not already have an active outgoing offer
        - Recipient must exist
        - For doubles offers (DBL-4): partner_uid must exist as a user, and
          the source broadcast (if any) must have match_type=doubles
        """
        # Get sender
        sender_doc = self.users_repo.get_user_doc(from_uid)
        if not sender_doc:
            raise ValueError("Sender not found")

        sender_play_tab = sender_doc.get("playTab", {}) or {}
        sender_state = sender_play_tab.get("state", "DISCOVERY")
        if sender_play_tab.get("activeOutgoingOfferId"):
            raise ValueError("Sender already has an active outgoing offer")

        if sender_state not in ["DISCOVERY", "BROADCAST_ACTIVE"]:
            raise ValueError(f"Cannot send offer: sender is in {sender_state} state")

        if sender_play_tab.get("activeOutgoingOfferId"):
            raise ValueError("Sender already has an active outgoing offer")

        # Get recipient
        recipient_doc = self.users_repo.get_user_doc(request.to_uid)
        if not recipient_doc:
            raise ValueError("Recipient not found")

        recipient_play_tab = recipient_doc.get("playTab", {}) or {}
        recipient_state = recipient_play_tab.get("state", "DISCOVERY")
        recipient_broadcast_id = recipient_play_tab.get("activeBroadcastId")

        if request.source_broadcast_id and request.source_broadcast_id != recipient_broadcast_id:
            raise ValueError("sourceBroadcastId is not the recipient's active broadcast")

        # Doubles validation (DBL-4).
        # 1. If challenging a broadcast, the offer's match_type must match the
        #    broadcast's match_type (you can't send a singles challenge to a
        #    doubles broadcast or vice versa).
        # 2. If match_type=doubles, partner_uid must reference an existing user
        #    distinct from sender, recipient, and the recipient's broadcast
        #    partner (when present).
        # 3. find_fourth broadcasts are not yet supported by accept_offer; we
        #    reject the offer up front to keep the surface honest.
        source_broadcast = (
            self.broadcasts_repo.get_by_id(request.source_broadcast_id)
            if request.source_broadcast_id
            else None
        )
        if source_broadcast is not None:
            if source_broadcast.match_type != request.match_type:
                msg = (
                    f"Offer match_type={request.match_type.value} does not match "
                    f"broadcast match_type={source_broadcast.match_type.value}"
                )
                raise ValueError(msg)
            if request.match_type == MatchTypeEnum.DOUBLES and (
                source_broadcast.broadcast_type.value == "find_fourth"
            ):
                msg = "find_fourth broadcasts are not yet supported for offers"
                raise ValueError(msg)

        if request.match_type == MatchTypeEnum.DOUBLES:
            partner_uid = request.partner_uid
            if not partner_uid:
                # Defensive: model validator catches this, but keep the service
                # layer honest in case anyone calls send_offer with a hand-built
                # request that bypasses the validator.
                raise ValueError("match_type=doubles requires partner_uid")
            # Direct doubles challenges (no source broadcast) are not yet
            # supported — without a broadcast we have no signal of who the
            # recipient's partner is. Reject up front so we never create an
            # offer that accept_offer cannot satisfy (which would otherwise
            # leave both users stuck in pending states).
            if source_broadcast is None or not source_broadcast.partner_uid:
                msg = "Doubles offers require a source broadcast carrying the recipient's partner"
                raise ValueError(msg)
            distinct = {from_uid, request.to_uid, partner_uid, source_broadcast.partner_uid}
            if len(distinct) != 4:
                msg = "Doubles offer participants must all be distinct"
                raise ValueError(msg)
            partner_doc = self.users_repo.get_user_doc(partner_uid)
            if not partner_doc:
                raise ValueError("Partner user not found")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=5)  # 5 minute TTL

        # Get user profiles for denormalized fields
        sender_name = sender_doc.get("name", "")
        recipient_name = recipient_doc.get("name", "")
        sender_rankings = sender_doc.get("rankings", {}) or {}
        recipient_rankings = recipient_doc.get("rankings", {}) or {}
        sender_ranking = sender_rankings.get(request.sport.value)
        recipient_ranking = recipient_rankings.get(request.sport.value)

        # Singles offers never persist a partner_uid — even if the request
        # somehow leaked one past the validator. Mirror DBL-3's defensive
        # cleanup on the broadcast side.
        partner_uid = request.partner_uid
        if request.match_type == MatchTypeEnum.SINGLES:
            partner_uid = None

        # Build offer doc (camelCase)
        offer_data = {
            "fromUid": from_uid,
            "fromName": sender_name,
            "fromRanking": sender_ranking,
            "toUid": request.to_uid,
            "toName": recipient_name,
            "toRanking": recipient_ranking,
            "sport": request.sport.value,
            "matchType": request.match_type.value,
            "partnerUid": partner_uid,
            "proposedTime": request.proposed_time,
            "courtLocation": request.court_location,
            "venueRef": request.venue_ref.model_dump(by_alias=True) if request.venue_ref else None,
            "sourceBroadcastId": request.source_broadcast_id,
            "message": request.message,
            "status": "pending",
            "expiresAt": expires_at,
            "createdAt": now,
            "matchId": None,
        }

        # Transactional write
        transaction = self.client.transaction()

        @firestore.transactional
        def send_offer_txn(txn):
            # Create offer
            offer_ref = self.client.collection("offers").document()
            txn.set(offer_ref, offer_data)

            # Update sender playTab
            sender_ref = self.client.collection("users").document(from_uid)
            sender_updates = {
                "playTab.state": "OUTGOING_OFFER_PENDING",
                "playTab.activeOutgoingOfferId": offer_ref.id,
                "playTab.updatedAt": now,
            }
            txn.update(sender_ref, sender_updates)

            # Update recipient playTab
            recipient_ref = self.client.collection("users").document(request.to_uid)
            current_pending = recipient_play_tab.get("pendingIncomingOfferIds", [])
            new_pending = current_pending + [offer_ref.id]

            recipient_updates = {
                "playTab.pendingIncomingOfferIds": new_pending,
                "playTab.updatedAt": now,
            }

            # If recipient is in DISCOVERY, transition to INCOMING_OFFER_PENDING
            if recipient_state == "DISCOVERY":
                recipient_updates["playTab.state"] = "INCOMING_OFFER_PENDING"
            # If recipient is in BROADCAST_ACTIVE, state stays (offer queues)

            txn.update(recipient_ref, recipient_updates)

            return offer_ref.id

        offer_id = send_offer_txn(transaction)

        return SendOfferResponse(
            offer_id=offer_id,
            to_uid=request.to_uid,
            to_name=recipient_name,
            sport=request.sport,
            match_type=request.match_type,
            partner_uid=partner_uid,
            proposed_time=request.proposed_time,
            status=OfferStatusEnum.PENDING,
            expires_at=expires_at,
            created_at=now,
        )

    # ===== POST /me/offers/{offer_id}/accept =====

    def accept_offer(self, uid: str, offer_id: str) -> OfferActionResponse:
        """
        Accept an incoming offer. Creates a scheduled match.

        Preconditions:
        - Offer must exist, be pending, and not expired
        - User must be the recipient (toUid)

        Doubles (DBL-4): when ``offer.match_type == doubles``, the new match is
        built from 4 distinct participants — Team A is the broadcaster + their
        partner (from the source broadcast), Team B is the challenger + their
        partner (from the offer). All 4 users transition to MATCH_SCHEDULED.
        """
        offer = self.offers_repo.get_by_id(offer_id)
        if not offer:
            raise ValueError("Offer not found")

        if offer.to_uid != uid:
            raise ValueError("You are not the recipient of this offer")

        if offer.status != OfferStatusEnum.PENDING:
            raise ValueError(f"Offer is {offer.status}, not pending")

        now = datetime.now(timezone.utc)
        if offer.expires_at < now:
            raise ValueError("Offer has expired")

        # Get both users
        recipient_doc = self.users_repo.get_user_doc(uid)
        sender_doc = self.users_repo.get_user_doc(offer.from_uid)

        if not recipient_doc or not sender_doc:
            raise ValueError("User not found")

        recipient_play_tab = recipient_doc.get("playTab", {}) or {}

        recipient_broadcast_id = recipient_play_tab.get("activeBroadcastId")
        all_pending_offers = recipient_play_tab.get("pendingIncomingOfferIds", [])
        source_broadcast = (
            self.broadcasts_repo.get_by_id(offer.source_broadcast_id)
            if offer.source_broadcast_id
            else None
        )
        venue_ref = (
            source_broadcast.venue_ref
            if source_broadcast and source_broadcast.venue_ref
            else offer.venue_ref
        )

        # Cached display names (short form) for the new match's participants —
        # required by the DBL-1 ParticipantEntry contract so doubles UIs can
        # render team labels without an extra users lookup.
        sender_display_name = _short_display_name(sender_doc.get("name", "") or "")
        recipient_display_name = _short_display_name(recipient_doc.get("name", "") or "")

        match_id = f"match_{offer_id}"  # Placeholder

        # Branch by match_type. Doubles requires 4 distinct UIDs and team
        # assignments. find_fourth is rejected at acceptance time — its team
        # assignment is a follow-up (the issue allows scoping to
        # singles/doubles_team_pair when the alternative would meaningfully
        # expand scope).
        if offer.match_type == MatchTypeEnum.DOUBLES:
            if source_broadcast is not None and (
                source_broadcast.broadcast_type.value == "find_fourth"
            ):
                msg = "find_fourth doubles acceptance is not yet supported"
                raise ValueError(msg)

            # Team A = broadcaster (recipient) + recipient's partner
            # Team B = challenger (sender) + sender's partner (from offer)
            recipient_partner_uid: str | None = None
            if source_broadcast is not None:
                recipient_partner_uid = source_broadcast.partner_uid
            if not recipient_partner_uid:
                # Direct-challenge case: no source_broadcast carrying the
                # recipient's partner. Doubles direct challenges are not
                # supported yet — without a broadcast we have no signal of who
                # the recipient's partner is.
                msg = "Doubles offers require a source broadcast carrying the recipient's partner"
                raise ValueError(msg)
            sender_partner_uid = offer.partner_uid
            if not sender_partner_uid:
                # Should not happen — Offer's model validator enforces this.
                msg = "Doubles offer is missing partner_uid"
                raise ValueError(msg)

            uids = [
                offer.to_uid,  # broadcaster (recipient)
                recipient_partner_uid,
                offer.from_uid,  # challenger (sender)
                sender_partner_uid,
            ]
            if len(set(uids)) != 4:
                raise ValueError("Doubles match requires 4 distinct participants")

            recipient_partner_doc = self.users_repo.get_user_doc(recipient_partner_uid)
            sender_partner_doc = self.users_repo.get_user_doc(sender_partner_uid)
            if not recipient_partner_doc or not sender_partner_doc:
                raise ValueError("Partner user not found")

            recipient_partner_display_name = _short_display_name(
                recipient_partner_doc.get("name", "") or ""
            )
            sender_partner_display_name = _short_display_name(
                sender_partner_doc.get("name", "") or ""
            )

            participants: list[dict[str, Any]] = [
                {
                    "uid": offer.to_uid,
                    "team": "A",
                    "role": ParticipantRoleEnum.PLAYER.value,
                    "displayName": recipient_display_name,
                },
                {
                    "uid": recipient_partner_uid,
                    "team": "A",
                    "role": ParticipantRoleEnum.PLAYER.value,
                    "displayName": recipient_partner_display_name,
                },
                {
                    "uid": offer.from_uid,
                    "team": "B",
                    "role": ParticipantRoleEnum.PLAYER.value,
                    "displayName": sender_display_name,
                },
                {
                    "uid": sender_partner_uid,
                    "team": "B",
                    "role": ParticipantRoleEnum.PLAYER.value,
                    "displayName": sender_partner_display_name,
                },
            ]
            match_data: dict[str, Any] = {
                "sport": offer.sport.value,
                "status": MatchStatusEnum.SCHEDULED.value,
                "matchType": MatchTypeEnum.DOUBLES.value,
                "scheduledAt": offer.proposed_time,
                "participants": participants,
                "participantUids": uids,
                # participant_pair is meaningless for 4-player matches.
                "participantPair": None,
                "resultSubmittedBy": [],
                "leagueId": None,
                "courtId": None,
                "venueRef": venue_ref.model_dump(by_alias=True) if venue_ref else None,
            }
            participant_uids_to_update = uids
        else:
            match_data = {
                "sport": offer.sport.value,
                "status": MatchStatusEnum.SCHEDULED.value,
                "matchType": MatchTypeEnum.SINGLES.value,
                "scheduledAt": offer.proposed_time,
                "participants": [
                    {
                        "uid": offer.from_uid,
                        "team": None,
                        "role": ParticipantRoleEnum.PLAYER.value,
                        "displayName": sender_display_name,
                    },
                    {
                        "uid": offer.to_uid,
                        "team": None,
                        "role": ParticipantRoleEnum.PLAYER.value,
                        "displayName": recipient_display_name,
                    },
                ],
                "participantUids": [offer.from_uid, offer.to_uid],
                "participantPair": compute_participant_pair([offer.from_uid, offer.to_uid]),
                "resultSubmittedBy": [],
                "leagueId": None,
                "courtId": None,
                "venueRef": venue_ref.model_dump(by_alias=True) if venue_ref else None,
            }
            participant_uids_to_update = [offer.from_uid, offer.to_uid]

        # Transactional write
        transaction = self.client.transaction()

        @firestore.transactional
        def accept_offer_txn(txn):
            # Update offer
            offer_ref = self.client.collection("offers").document(offer_id)
            txn.update(offer_ref, {"status": "accepted", "matchId": match_id})

            match_ref = self.client.collection("matches").document(match_id)
            txn.set(match_ref, match_data)

            # Cancel recipient's broadcast if active
            if recipient_broadcast_id:
                broadcast_ref = self.client.collection("broadcasts").document(
                    recipient_broadcast_id
                )
                txn.update(broadcast_ref, {"status": "matched"})

            # Decline all other pending offers
            for other_offer_id in all_pending_offers:
                if other_offer_id != offer_id:
                    other_offer_ref = self.client.collection("offers").document(other_offer_id)
                    txn.update(other_offer_ref, {"status": "declined"})

            # Update playTab for every participant. For singles this is the
            # sender + recipient; for doubles it's all 4 players (DBL-4).
            for participant_uid in participant_uids_to_update:
                participant_ref = self.client.collection("users").document(participant_uid)
                txn.update(
                    participant_ref,
                    {
                        "playTab.state": "MATCH_SCHEDULED",
                        "playTab.activeMatchId": match_id,
                        "playTab.activeBroadcastId": None,
                        "playTab.activeOutgoingOfferId": None,
                        "playTab.pendingIncomingOfferIds": [],
                        "playTab.updatedAt": now,
                    },
                )

        accept_offer_txn(transaction)

        return OfferActionResponse(
            offer_id=offer_id,
            status=OfferStatusEnum.ACCEPTED,
            match_id=match_id,
            scheduled_at=offer.proposed_time,
        )

    # ===== POST /me/offers/{offer_id}/decline =====

    def decline_offer(self, uid: str, offer_id: str) -> OfferActionResponse:
        """
        Decline an incoming offer.

        Preconditions:
        - Offer must exist and be pending
        - User must be the recipient
        """
        offer = self.offers_repo.get_by_id(offer_id)
        if not offer:
            raise ValueError("Offer not found")

        if offer.to_uid != uid:
            raise ValueError("You are not the recipient of this offer")

        if offer.status != OfferStatusEnum.PENDING:
            raise ValueError(f"Offer is {offer.status}, not pending")

        recipient_doc = self.users_repo.get_user_doc(uid)
        sender_doc = self.users_repo.get_user_doc(offer.from_uid)

        if not recipient_doc or not sender_doc:
            raise ValueError("User not found")

        recipient_play_tab = recipient_doc.get("playTab", {}) or {}
        sender_play_tab = sender_doc.get("playTab", {}) or {}

        pending_offers = recipient_play_tab.get("pendingIncomingOfferIds", [])
        remaining_offers = [oid for oid in pending_offers if oid != offer_id]

        recipient_broadcast_id = recipient_play_tab.get("activeBroadcastId")
        sender_broadcast_id = sender_play_tab.get("activeBroadcastId")

        now = datetime.now(timezone.utc)

        # Transactional write
        transaction = self.client.transaction()

        @firestore.transactional
        def decline_offer_txn(txn):
            # Update offer
            offer_ref = self.client.collection("offers").document(offer_id)
            txn.update(offer_ref, {"status": "declined"})

            # Update recipient playTab
            recipient_ref = self.client.collection("users").document(uid)
            recipient_updates = {
                "playTab.pendingIncomingOfferIds": remaining_offers,
                "playTab.updatedAt": now,
            }

            # Recalculate recipient state
            if recipient_broadcast_id:
                recipient_updates["playTab.state"] = "BROADCAST_ACTIVE"
            elif remaining_offers:
                recipient_updates["playTab.state"] = "INCOMING_OFFER_PENDING"
            else:
                recipient_updates["playTab.state"] = "DISCOVERY"

            txn.update(recipient_ref, recipient_updates)

            # Update sender playTab (if this was their active outgoing offer)
            if sender_play_tab.get("activeOutgoingOfferId") == offer_id:
                sender_ref = self.client.collection("users").document(offer.from_uid)
                sender_updates = {
                    "playTab.activeOutgoingOfferId": None,
                    "playTab.updatedAt": now,
                }
                # Recalculate sender state
                if sender_broadcast_id:
                    sender_updates["playTab.state"] = "BROADCAST_ACTIVE"
                else:
                    sender_updates["playTab.state"] = "DISCOVERY"
                txn.update(sender_ref, sender_updates)

        decline_offer_txn(transaction)

        return OfferActionResponse(
            offer_id=offer_id,
            status=OfferStatusEnum.DECLINED,
        )

    # ===== POST /me/offers/{offer_id}/cancel =====

    def cancel_offer(self, uid: str, offer_id: str) -> OfferActionResponse:
        """
        Cancel an outgoing offer (sender withdraws).

        Preconditions:
        - Offer must exist and be pending
        - User must be the sender
        """
        offer = self.offers_repo.get_by_id(offer_id)
        if not offer:
            raise ValueError("Offer not found")

        if offer.from_uid != uid:
            raise ValueError("You are not the sender of this offer")

        if offer.status != OfferStatusEnum.PENDING:
            raise ValueError(f"Offer is {offer.status}, not pending")

        sender_doc = self.users_repo.get_user_doc(uid)
        recipient_doc = self.users_repo.get_user_doc(offer.to_uid)

        if not sender_doc or not recipient_doc:
            raise ValueError("User not found")

        sender_play_tab = sender_doc.get("playTab", {}) or {}
        recipient_play_tab = recipient_doc.get("playTab", {}) or {}

        sender_broadcast_id = sender_play_tab.get("activeBroadcastId")
        recipient_broadcast_id = recipient_play_tab.get("activeBroadcastId")

        pending_offers = recipient_play_tab.get("pendingIncomingOfferIds", [])
        remaining_offers = [oid for oid in pending_offers if oid != offer_id]

        now = datetime.now(timezone.utc)

        # Transactional write
        transaction = self.client.transaction()

        @firestore.transactional
        def cancel_offer_txn(txn):
            # Update offer
            offer_ref = self.client.collection("offers").document(offer_id)
            txn.update(offer_ref, {"status": "cancelled"})

            # Update sender playTab
            sender_ref = self.client.collection("users").document(uid)
            sender_updates = {
                "playTab.activeOutgoingOfferId": None,
                "playTab.updatedAt": now,
            }
            # Recalculate sender state
            if sender_broadcast_id:
                sender_updates["playTab.state"] = "BROADCAST_ACTIVE"
            else:
                sender_updates["playTab.state"] = "DISCOVERY"
            txn.update(sender_ref, sender_updates)

            # Update recipient playTab
            recipient_ref = self.client.collection("users").document(offer.to_uid)
            recipient_updates = {
                "playTab.pendingIncomingOfferIds": remaining_offers,
                "playTab.updatedAt": now,
            }
            # Recalculate recipient state
            if recipient_broadcast_id:
                recipient_updates["playTab.state"] = "BROADCAST_ACTIVE"
            elif remaining_offers:
                recipient_updates["playTab.state"] = "INCOMING_OFFER_PENDING"
            else:
                recipient_updates["playTab.state"] = "DISCOVERY"
            txn.update(recipient_ref, recipient_updates)

        cancel_offer_txn(transaction)

        return OfferActionResponse(
            offer_id=offer_id,
            status=OfferStatusEnum.CANCELLED,
        )
