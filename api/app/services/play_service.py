"""
PlayService - Business logic for Tab 1 PLAY matchmaking.

Handles:
- State computation and freshness reconciliation
- Transactional writes for state transitions
- Broadcast/offer/match lifecycle management
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import (
    BroadcastStatusEnum,
    OfferStatusEnum,
    PlayTabStateEnum,
)
from app.models.play import (
    Broadcast,
    BroadcastActivePayload,
    CreateBroadcastRequest,
    CreateBroadcastResponse,
    IncomingOfferPayload,
    MeStatePrimary,
    MeStateResponse,
    Offer,
    OfferActionResponse,
    OutgoingOfferPayload,
    PendingOfferSummary,
    SendOfferRequest,
    SendOfferResponse,
)
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo


class PlayService:
    """Service for Tab 1 PLAY business logic."""

    def __init__(
        self,
        users_repo: UsersRepo,
        broadcasts_repo: BroadcastsRepo,
        offers_repo: OffersRepo,
        firestore_client: firestore.Client,
    ):
        self.users_repo = users_repo
        self.broadcasts_repo = broadcasts_repo
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
                    ui_events.append({"type": "offer_expired", "message": "Your offer has expired."})
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
            + ([play_tab.get("activeOutgoingOfferId")] if play_tab.get("activeOutgoingOfferId") else []),
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
                        availability=broadcast.availability,
                        court_status=broadcast.court_status,
                        court_location=broadcast.court_location,
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

        # TODO: Handle MATCH_SCHEDULED and post-match states (future epic)

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
            raise ValueError(f"Cannot create broadcast: user is in {state} state, must be DISCOVERY")

        now = datetime.now(timezone.utc)
        if request.expires_at <= now:
            raise ValueError("expiresAt must be in the future")

        # Get user profile for denormalized fields
        user_name = user_doc.get("name", "")
        rankings = user_doc.get("rankings", {}) or {}
        sport_ranking = rankings.get(request.sport.value)

        # Build broadcast doc (camelCase for Firestore)
        broadcast_data = {
            "ownerUid": uid,
            "ownerName": user_name,
            "ownerRanking": sport_ranking,
            "sport": request.sport.value,
            "availability": request.availability.value,
            "courtStatus": request.court_status.value,
            "courtLocation": request.court_location,
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
        """
        # Get sender
        sender_doc = self.users_repo.get_user_doc(from_uid)
        if not sender_doc:
            raise ValueError("Sender not found")

        sender_play_tab = sender_doc.get("playTab", {}) or {}
        sender_state = sender_play_tab.get("state", "DISCOVERY")

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

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=5)  # 5 minute TTL

        # Get user profiles for denormalized fields
        sender_name = sender_doc.get("name", "")
        recipient_name = recipient_doc.get("name", "")
        sender_rankings = sender_doc.get("rankings", {}) or {}
        recipient_rankings = recipient_doc.get("rankings", {}) or {}
        sender_ranking = sender_rankings.get(request.sport.value)
        recipient_ranking = recipient_rankings.get(request.sport.value)

        # Build offer doc (camelCase)
        offer_data = {
            "fromUid": from_uid,
            "fromName": sender_name,
            "fromRanking": sender_ranking,
            "toUid": request.to_uid,
            "toName": recipient_name,
            "toRanking": recipient_ranking,
            "sport": request.sport.value,
            "proposedTime": request.proposed_time,
            "courtLocation": request.court_location,
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
        sender_play_tab = sender_doc.get("playTab", {}) or {}

        recipient_broadcast_id = recipient_play_tab.get("activeBroadcastId")
        all_pending_offers = recipient_play_tab.get("pendingIncomingOfferIds", [])

        # TODO: Create match doc (future epic - for now just update offer + users)
        match_id = f"match_{offer_id}"  # Placeholder

        # Transactional write
        transaction = self.client.transaction()

        @firestore.transactional
        def accept_offer_txn(txn):
            # Update offer
            offer_ref = self.client.collection("offers").document(offer_id)
            txn.update(offer_ref, {"status": "accepted", "matchId": match_id})

            # TODO: Create match doc
            # match_ref = self.client.collection("matches").document()
            # txn.set(match_ref, {...})

            # Cancel recipient's broadcast if active
            if recipient_broadcast_id:
                broadcast_ref = self.client.collection("broadcasts").document(recipient_broadcast_id)
                txn.update(broadcast_ref, {"status": "matched"})

            # Decline all other pending offers
            for other_offer_id in all_pending_offers:
                if other_offer_id != offer_id:
                    other_offer_ref = self.client.collection("offers").document(other_offer_id)
                    txn.update(other_offer_ref, {"status": "declined"})

            # Update recipient playTab
            recipient_ref = self.client.collection("users").document(uid)
            txn.update(
                recipient_ref,
                {
                    "playTab.state": "MATCH_SCHEDULED",
                    "playTab.activeMatchId": match_id,
                    "playTab.activeBroadcastId": None,
                    "playTab.activeOutgoingOfferId": None,
                    "playTab.pendingIncomingOfferIds": [],
                    "playTab.updatedAt": now,
                },
            )

            # Update sender playTab
            sender_ref = self.client.collection("users").document(offer.from_uid)
            txn.update(
                sender_ref,
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
