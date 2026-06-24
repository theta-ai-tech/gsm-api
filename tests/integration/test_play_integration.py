"""
Integration tests for Tab 1 PLAY matchmaking.

Tests verify end-to-end behavior of PlayService against the real Firestore
emulator, including state transitions, transactions, and freshness
reconciliation.

Requires: FIRESTORE_EMULATOR_HOST env var set (e.g. via `make emu-all`)
"""

import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.models.common import GeoCoordinates, VenueRef
from app.models.enums import (
    AvailabilityEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    MatchTypeEnum,
    PlayTabStateEnum,
    SportEnum,
)
from app.models.play import (
    BroadcastLocation,
    CreateBroadcastRequest,
    GeoLocation,
    SendOfferRequest,
)
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.play_service import PlayService

pytestmark = [pytest.mark.integration]


# ===== Helpers =====


def make_play_service(db) -> PlayService:
    """Create a PlayService backed by real repos against the emulator."""
    return PlayService(
        UsersRepo(db),
        BroadcastsRepo(db),
        MatchesRepo(db),
        OffersRepo(db),
        db,
        region_config_repo=RegionConfigRepo(db),
    )


def seed_discovery_user(db, uid: str, name: str = "Test User") -> None:
    """Seed a user doc with DISCOVERY play tab state."""
    db.collection("users").document(uid).set(
        {
            "name": name,
            "email": f"{uid}@test.com",
            "rankings": {
                "tennis": {"sport": "tennis", "pts": 1200, "globalRanking": 42}
            },
            "playTab": {
                "state": "DISCOVERY",
                "updatedAt": datetime.now(timezone.utc),
            },
        }
    )


def make_broadcast_request(
    hours_from_now: float = 2.0,
    venue_ref: VenueRef | None = None,
) -> CreateBroadcastRequest:
    """Return a standard CreateBroadcastRequest with future expiresAt."""
    return CreateBroadcastRequest(
        sport=SportEnum.TENNIS,
        availability=AvailabilityEnum.TODAY,
        court_status=CourtStatusEnum.HAVE_COURT,
        court_location="Central Park",
        venue_ref=venue_ref,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours_from_now),
        location=BroadcastLocation(area=10001),
    )


def make_offer_request(
    to_uid: str,
    venue_ref: VenueRef | None = None,
    source_broadcast_id: str | None = None,
) -> SendOfferRequest:
    """Return a standard SendOfferRequest."""
    return SendOfferRequest(
        to_uid=to_uid,
        sport=SportEnum.TENNIS,
        proposed_time=datetime.now(timezone.utc) + timedelta(hours=2),
        court_location="Central Park",
        venue_ref=venue_ref,
        source_broadcast_id=source_broadcast_id,
        message="Let's play!",
    )


def get_play_tab(db, uid: str) -> dict:
    """Fetch the playTab sub-dict for a user."""
    doc = db.collection("users").document(uid).get()
    return doc.to_dict().get("playTab", {}) if doc.exists else {}


# ===== Cleanup =====


@pytest.fixture(autouse=True)
def _cleanup_play_collections(db):
    """Delete broadcasts and offers after each test (users handled by conftest)."""
    yield
    for doc in db.collection("broadcasts").stream():
        doc.reference.delete()
    for doc in db.collection("offers").stream():
        doc.reference.delete()
    for doc in db.collection("matches").stream():
        doc.reference.delete()


# ===== Test: Full Broadcast Flow =====


class TestFullBroadcastFlow:
    def test_full_broadcast_flow(self, db):
        """Alice creates broadcast → BROADCAST_ACTIVE → cancels → DISCOVERY."""
        alice_uid = "alice_broadcast_flow"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        # Create broadcast
        response = service.create_broadcast(alice_uid, make_broadcast_request())
        broadcast_id = response.broadcast_id
        assert broadcast_id

        # Alice is BROADCAST_ACTIVE
        play_tab = get_play_tab(db, alice_uid)
        assert play_tab["state"] == "BROADCAST_ACTIVE"
        assert play_tab["activeBroadcastId"] == broadcast_id

        # Broadcast doc is active
        broadcast_doc = db.collection("broadcasts").document(broadcast_id).get()
        assert broadcast_doc.exists
        assert broadcast_doc.to_dict()["status"] == "active"

        # Alice cancels
        service.cancel_broadcast(alice_uid)

        # Alice is DISCOVERY
        play_tab = get_play_tab(db, alice_uid)
        assert play_tab["state"] == "DISCOVERY"
        assert play_tab.get("activeBroadcastId") is None

        # Broadcast doc is cancelled
        broadcast_doc = db.collection("broadcasts").document(broadcast_id).get()
        assert broadcast_doc.to_dict()["status"] == "cancelled"

    def test_cancel_broadcast_with_pending_offers(self, db):
        """Cancelling broadcast declines all pending offers atomically."""
        alice_uid = "alice_cancel_with_offers"
        bob_uid = "bob_cancel_with_offers"
        charlie_uid = "charlie_cancel_with_offers"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, charlie_uid, "Charlie")
        service = make_play_service(db)

        service.create_broadcast(alice_uid, make_broadcast_request())

        bob_offer = service.send_offer(bob_uid, make_offer_request(alice_uid))
        charlie_offer = service.send_offer(charlie_uid, make_offer_request(alice_uid))

        # Verify 2 pending offers queued
        play_tab = get_play_tab(db, alice_uid)
        assert len(play_tab["pendingIncomingOfferIds"]) == 2

        # Alice cancels broadcast
        service.cancel_broadcast(alice_uid)

        # Both offers → declined
        bob_doc = db.collection("offers").document(bob_offer.offer_id).get()
        charlie_doc = db.collection("offers").document(charlie_offer.offer_id).get()
        assert bob_doc.to_dict()["status"] == "declined"
        assert charlie_doc.to_dict()["status"] == "declined"

        # Alice back to DISCOVERY with cleared pending list
        play_tab = get_play_tab(db, alice_uid)
        assert play_tab["state"] == "DISCOVERY"
        assert play_tab.get("pendingIncomingOfferIds") == []

    def test_cannot_create_broadcast_when_already_active(self, db):
        """User in BROADCAST_ACTIVE cannot create another broadcast."""
        alice_uid = "alice_double_broadcast"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        service.create_broadcast(alice_uid, make_broadcast_request())

        with pytest.raises(ValueError, match="BROADCAST_ACTIVE"):
            service.create_broadcast(alice_uid, make_broadcast_request())


# ===== Test: Doubles Broadcast Fields (DBL-3) =====


class TestDoublesBroadcastFields:
    def test_doubles_find_opponent_persists_partner_and_surfaces_in_payload(self, db):
        """Doubles + find_opponent broadcast persists matchType/broadcastType/
        partnerUid in Firestore and the BROADCAST_ACTIVE discovery payload
        exposes them so mobile can render team labels."""
        alice_uid = "alice_doubles_find_opponent"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        request = CreateBroadcastRequest(
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
            partner_uid="user_partner",
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            location=BroadcastLocation(area=10001),
        )

        response = service.create_broadcast(alice_uid, request)
        assert response.match_type == MatchTypeEnum.DOUBLES
        assert response.broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
        assert response.partner_uid == "user_partner"

        # Firestore document carries the camelCase fields.
        doc = (
            db.collection("broadcasts").document(response.broadcast_id).get().to_dict()
        )
        assert doc["matchType"] == "doubles"
        assert doc["broadcastType"] == "find_opponent"
        assert doc["partnerUid"] == "user_partner"

        # /me/state returns BROADCAST_ACTIVE with the doubles fields surfaced.
        state = service.get_me_state(alice_uid)
        assert state.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert state.payload["match_type"] == "doubles"
        assert state.payload["broadcast_type"] == "find_opponent"
        assert state.payload["partner_uid"] == "user_partner"

    def test_doubles_find_fourth_without_partner_persisted(self, db):
        """Doubles + find_fourth without a partner_uid is allowed end-to-end."""
        alice_uid = "alice_doubles_find_fourth"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        request = CreateBroadcastRequest(
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            location=BroadcastLocation(area=10001),
        )

        response = service.create_broadcast(alice_uid, request)
        doc = (
            db.collection("broadcasts").document(response.broadcast_id).get().to_dict()
        )
        assert doc["matchType"] == "doubles"
        assert doc["broadcastType"] == "find_fourth"
        assert doc["partnerUid"] is None

        state = service.get_me_state(alice_uid)
        assert state.payload["broadcast_type"] == "find_fourth"
        assert state.payload["partner_uid"] is None

    def test_singles_broadcast_default_fields_surface(self, db):
        """Default (no doubles fields) singles broadcast surfaces the singles
        defaults in the discovery payload — backwards compatibility for
        existing singles flows."""
        alice_uid = "alice_singles_default"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        response = service.create_broadcast(alice_uid, make_broadcast_request())
        doc = (
            db.collection("broadcasts").document(response.broadcast_id).get().to_dict()
        )
        assert doc["matchType"] == "singles"
        assert doc["broadcastType"] == "find_opponent"
        assert doc["partnerUid"] is None

        state = service.get_me_state(alice_uid)
        assert state.payload["match_type"] == "singles"
        assert state.payload["broadcast_type"] == "find_opponent"
        assert state.payload["partner_uid"] is None


# ===== Test: Doubles Offer + Acceptance Flow (DBL-4) =====


class TestDoublesOfferAcceptanceFlow:
    def test_doubles_offer_creates_4_participant_match(self, db):
        """End-to-end: Bob (broadcaster) + Dave vs Alice (challenger) + Charlie.

        Bob broadcasts a doubles + find_opponent broadcast with Dave as
        partner. Alice sends a doubles offer with Charlie as partner. Bob
        accepts → 4-participant match created, all 4 users → MATCH_SCHEDULED.
        """
        bob_uid = "bob_doubles_4p"
        alice_uid = "alice_doubles_4p"
        dave_uid = "dave_doubles_4p"
        charlie_uid = "charlie_doubles_4p"
        seed_discovery_user(db, bob_uid, "Bob Smith")
        seed_discovery_user(db, alice_uid, "Alice King")
        seed_discovery_user(db, dave_uid, "Dave Knight")
        seed_discovery_user(db, charlie_uid, "Charlie Owen")

        service = make_play_service(db)

        # Bob broadcasts doubles + find_opponent with Dave as partner.
        broadcast_resp = service.create_broadcast(
            bob_uid,
            CreateBroadcastRequest(
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
                broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
                partner_uid=dave_uid,
                availability=AvailabilityEnum.TODAY,
                court_status=CourtStatusEnum.NEED_COURT,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            ),
        )

        # Alice sends a doubles offer with Charlie as her partner.
        offer_resp = service.send_offer(
            alice_uid,
            SendOfferRequest(
                to_uid=bob_uid,
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
                partner_uid=charlie_uid,
                proposed_time=datetime.now(timezone.utc) + timedelta(hours=2),
                source_broadcast_id=broadcast_resp.broadcast_id,
                message="Doubles?",
            ),
        )

        # Offer doc carries the doubles fields.
        offer_doc = (
            db.collection("offers").document(offer_resp.offer_id).get().to_dict()
        )
        assert offer_doc["matchType"] == "doubles"
        assert offer_doc["partnerUid"] == charlie_uid

        # Bob accepts.
        accept_resp = service.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id
        assert match_id

        # Match doc has 4 participants with team A / team B.
        match_doc = db.collection("matches").document(match_id).get().to_dict()
        assert match_doc["matchType"] == "doubles"
        participants = match_doc["participants"]
        assert len(participants) == 4
        by_uid = {p["uid"]: p for p in participants}
        assert by_uid[bob_uid]["team"] == "A"
        assert by_uid[dave_uid]["team"] == "A"
        assert by_uid[alice_uid]["team"] == "B"
        assert by_uid[charlie_uid]["team"] == "B"
        # Cached short display names persisted.
        assert by_uid[bob_uid]["displayName"] == "Bob S."
        assert by_uid[alice_uid]["displayName"] == "Alice K."
        assert by_uid[dave_uid]["displayName"] == "Dave K."
        assert by_uid[charlie_uid]["displayName"] == "Charlie O."

        # All 4 users transitioned to MATCH_SCHEDULED with the new match id.
        for uid in (bob_uid, alice_uid, dave_uid, charlie_uid):
            tab = get_play_tab(db, uid)
            assert tab["state"] == "MATCH_SCHEDULED", f"{uid} not MATCH_SCHEDULED"
            assert tab["activeMatchId"] == match_id

        # Broadcast doc is matched.
        bc = (
            db.collection("broadcasts")
            .document(broadcast_resp.broadcast_id)
            .get()
            .to_dict()
        )
        assert bc["status"] == "matched"

    def test_doubles_offer_rejected_when_match_type_mismatches_broadcast(self, db):
        """Singles offer against a doubles broadcast → ValueError."""
        bob_uid = "bob_dbl_mismatch"
        alice_uid = "alice_dbl_mismatch"
        dave_uid = "dave_dbl_mismatch"
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, dave_uid, "Dave")

        service = make_play_service(db)
        broadcast_resp = service.create_broadcast(
            bob_uid,
            CreateBroadcastRequest(
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
                broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
                partner_uid=dave_uid,
                availability=AvailabilityEnum.TODAY,
                court_status=CourtStatusEnum.NEED_COURT,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            ),
        )

        with pytest.raises(ValueError, match="does not match broadcast match_type"):
            service.send_offer(
                alice_uid,
                SendOfferRequest(
                    to_uid=bob_uid,
                    sport=SportEnum.PADEL,
                    match_type=MatchTypeEnum.SINGLES,
                    proposed_time=datetime.now(timezone.utc) + timedelta(hours=2),
                    source_broadcast_id=broadcast_resp.broadcast_id,
                ),
            )


# ===== Test: Direct Challenge Flow =====


class TestDirectChallengeFlow:
    def test_direct_challenge_flow(self, db):
        """Alice sends offer → Bob accepts → both MATCH_SCHEDULED."""
        alice_uid = "alice_challenge"
        bob_uid = "bob_challenge"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        # Alice sends offer to Bob
        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        # Alice → OUTGOING_OFFER_PENDING
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "OUTGOING_OFFER_PENDING"
        assert alice_tab["activeOutgoingOfferId"] == offer_id

        # Bob → INCOMING_OFFER_PENDING
        bob_tab = get_play_tab(db, bob_uid)
        assert bob_tab["state"] == "INCOMING_OFFER_PENDING"
        assert offer_id in bob_tab["pendingIncomingOfferIds"]

        # Bob accepts
        accept_resp = service.accept_offer(bob_uid, offer_id)
        match_id = accept_resp.match_id
        assert match_id

        # Both → MATCH_SCHEDULED with same match ID
        alice_tab = get_play_tab(db, alice_uid)
        bob_tab = get_play_tab(db, bob_uid)
        assert alice_tab["state"] == "MATCH_SCHEDULED"
        assert bob_tab["state"] == "MATCH_SCHEDULED"
        assert alice_tab["activeMatchId"] == match_id
        assert bob_tab["activeMatchId"] == match_id

        # Offer doc → accepted
        offer_doc = db.collection("offers").document(offer_id).get()
        assert offer_doc.to_dict()["status"] == "accepted"
        assert offer_doc.to_dict()["matchId"] == match_id

        match_doc = db.collection("matches").document(match_id).get()
        match_data = match_doc.to_dict() or {}
        assert match_data["status"] == "scheduled"
        assert match_data["participantUids"] == [alice_uid, bob_uid]
        assert match_data["venueRef"] is None

    def test_accept_offer_propagates_source_broadcast_venue_ref_to_match(self, db):
        alice_uid = "alice_broadcast_venue"
        bob_uid = "bob_broadcast_venue"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")

        venue_ref = VenueRef(
            venue_id="ten_twenty_club",
            place_id=None,
            name="Ten Twenty Club",
            coordinates=GeoCoordinates(lat=37.8362, lng=23.7627),
        )
        service = make_play_service(db)
        broadcast_resp = service.create_broadcast(
            alice_uid,
            make_broadcast_request(venue_ref=venue_ref),
        )
        offer_resp = service.send_offer(
            bob_uid,
            make_offer_request(
                alice_uid,
                source_broadcast_id=broadcast_resp.broadcast_id,
            ),
        )
        accept_resp = service.accept_offer(alice_uid, offer_resp.offer_id)

        match_doc = db.collection("matches").document(accept_resp.match_id).get()
        match_data = match_doc.to_dict() or {}
        assert match_data["venueRef"]["venueId"] == "ten_twenty_club"
        assert match_data["venueRef"]["name"] == "Ten Twenty Club"

        alice_state = service.get_me_state(alice_uid)
        assert alice_state.mode == PlayTabStateEnum.MATCH_SCHEDULED
        assert alice_state.payload["venue_ref"]["venueId"] == "ten_twenty_club"

    def test_accept_offer_uses_offer_venue_ref_not_unrelated_broadcast(self, db):
        alice_uid = "alice_direct_offer_venue"
        bob_uid = "bob_direct_offer_venue"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")

        broadcast_venue = {
            "venueId": "ten_twenty_club",
            "placeId": None,
            "name": "Ten Twenty Club",
            "coordinates": {"lat": 37.8362, "lng": 23.7627},
        }
        direct_offer_venue = VenueRef(
            venue_id="byron_clay",
            place_id=None,
            name="Byron Clay Courts",
            coordinates=GeoCoordinates(lat=37.9838, lng=23.7275),
        )

        broadcast_id = "broadcast_alice_direct_offer"
        now = datetime.now(timezone.utc)
        db.collection("broadcasts").document(broadcast_id).set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "tennis",
                "availability": "today",
                "courtStatus": "have_court",
                "courtLocation": "Ten Twenty Club",
                "venueRef": broadcast_venue,
                "status": "active",
                "expiresAt": now + timedelta(hours=2),
                "createdAt": now,
                "location": {"area": 10001, "geo": None, "radiusKm": None},
            }
        )
        db.collection("users").document(alice_uid).update(
            {
                "playTab.state": "BROADCAST_ACTIVE",
                "playTab.activeBroadcastId": broadcast_id,
                "playTab.pendingIncomingOfferIds": [],
            }
        )

        service = make_play_service(db)
        offer_resp = service.send_offer(
            bob_uid,
            make_offer_request(alice_uid, venue_ref=direct_offer_venue),
        )
        accept_resp = service.accept_offer(alice_uid, offer_resp.offer_id)

        match_doc = db.collection("matches").document(accept_resp.match_id).get()
        match_data = match_doc.to_dict() or {}
        assert match_data["venueRef"]["venueId"] == "byron_clay"
        assert match_data["venueRef"]["name"] == "Byron Clay Courts"

    def test_direct_challenge_decline_flow(self, db):
        """Alice sends offer → Bob declines → Alice back to DISCOVERY."""
        alice_uid = "alice_decline"
        bob_uid = "bob_decline"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        service.decline_offer(bob_uid, offer_id)

        # Offer → declined
        offer_doc = db.collection("offers").document(offer_id).get()
        assert offer_doc.to_dict()["status"] == "declined"

        # Bob → DISCOVERY
        bob_tab = get_play_tab(db, bob_uid)
        assert bob_tab["state"] == "DISCOVERY"

        # Alice → DISCOVERY (offer cleared)
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "DISCOVERY"
        assert alice_tab.get("activeOutgoingOfferId") is None

    def test_direct_challenge_cancel_flow(self, db):
        """Alice sends offer → Alice cancels → both DISCOVERY."""
        alice_uid = "alice_cancel_offer"
        bob_uid = "bob_cancel_offer"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        service.cancel_offer(alice_uid, offer_id)

        # Offer → cancelled
        offer_doc = db.collection("offers").document(offer_id).get()
        assert offer_doc.to_dict()["status"] == "cancelled"

        # Alice → DISCOVERY
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "DISCOVERY"
        assert alice_tab.get("activeOutgoingOfferId") is None

        # Bob → DISCOVERY (offer removed from pending list)
        bob_tab = get_play_tab(db, bob_uid)
        assert bob_tab["state"] == "DISCOVERY"
        assert offer_id not in bob_tab.get("pendingIncomingOfferIds", [])


# ===== Test: Broadcast with Offer Queue =====


class TestBroadcastWithOfferQueue:
    def test_broadcast_with_offer_queue(self, db):
        """Alice broadcasts; Bob + Charlie offer; Alice accepts Bob → Charlie declined."""
        alice_uid = "alice_queue"
        bob_uid = "bob_queue"
        charlie_uid = "charlie_queue"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, charlie_uid, "Charlie")
        service = make_play_service(db)

        # Alice creates broadcast
        bc_resp = service.create_broadcast(alice_uid, make_broadcast_request())
        broadcast_id = bc_resp.broadcast_id

        # Bob sends offer to Alice (stays BROADCAST_ACTIVE)
        bob_offer = service.send_offer(bob_uid, make_offer_request(alice_uid))
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "BROADCAST_ACTIVE"
        assert bob_offer.offer_id in alice_tab["pendingIncomingOfferIds"]

        # Charlie sends offer to Alice
        charlie_offer = service.send_offer(charlie_uid, make_offer_request(alice_uid))
        alice_tab = get_play_tab(db, alice_uid)
        assert len(alice_tab["pendingIncomingOfferIds"]) == 2

        # Alice accepts Bob's offer
        service.accept_offer(alice_uid, bob_offer.offer_id)

        # Charlie's offer → declined
        charlie_doc = db.collection("offers").document(charlie_offer.offer_id).get()
        assert charlie_doc.to_dict()["status"] == "declined"

        # Broadcast → matched
        broadcast_doc = db.collection("broadcasts").document(broadcast_id).get()
        assert broadcast_doc.to_dict()["status"] == "matched"

        # Alice and Bob → MATCH_SCHEDULED
        alice_tab = get_play_tab(db, alice_uid)
        bob_tab = get_play_tab(db, bob_uid)
        assert alice_tab["state"] == "MATCH_SCHEDULED"
        assert bob_tab["state"] == "MATCH_SCHEDULED"

        # Alice's pending offers list cleared
        assert alice_tab.get("pendingIncomingOfferIds") == []

    def test_broadcast_sender_returns_to_broadcast_active_after_decline(self, db):
        """Declining an offer for a BROADCAST_ACTIVE user keeps them BROADCAST_ACTIVE."""
        alice_uid = "alice_stays_active"
        bob_uid = "bob_stays_active"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        service.create_broadcast(alice_uid, make_broadcast_request())
        bob_offer = service.send_offer(bob_uid, make_offer_request(alice_uid))

        service.decline_offer(alice_uid, bob_offer.offer_id)

        # Alice → back to BROADCAST_ACTIVE (not DISCOVERY)
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "BROADCAST_ACTIVE"
        assert bob_offer.offer_id not in alice_tab.get("pendingIncomingOfferIds", [])


# ===== Test: Freshness Reconciliation =====


class TestFreshnessReconciliation:
    def test_offer_expires_freshness_reconciliation(self, db):
        """Expired offer corrected when Bob calls get_me_state."""
        alice_uid = "alice_offer_expire"
        bob_uid = "bob_offer_expire"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        # Alice sends offer to Bob
        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        # Manually expire the offer
        db.collection("offers").document(offer_id).update(
            {"expiresAt": datetime.now(timezone.utc) - timedelta(minutes=1)}
        )

        # Bob's state read triggers freshness reconciliation
        bob_state = service.get_me_state(bob_uid)

        # Bob → DISCOVERY
        assert bob_state.mode == PlayTabStateEnum.DISCOVERY

        # Offer → expired
        offer_doc = db.collection("offers").document(offer_id).get()
        assert offer_doc.to_dict()["status"] == "expired"

        # UI event emitted
        assert any(e.type == "offer_expired" for e in bob_state.ui_events)

    def test_broadcast_expires_freshness_reconciliation(self, db):
        """Expired broadcast corrected when Alice calls get_me_state."""
        alice_uid = "alice_broadcast_expire"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        bc_resp = service.create_broadcast(alice_uid, make_broadcast_request())
        broadcast_id = bc_resp.broadcast_id

        # Manually expire the broadcast
        db.collection("broadcasts").document(broadcast_id).update(
            {"expiresAt": datetime.now(timezone.utc) - timedelta(minutes=1)}
        )

        # Alice's state read triggers freshness reconciliation
        alice_state = service.get_me_state(alice_uid)

        # Alice → DISCOVERY
        assert alice_state.mode == PlayTabStateEnum.DISCOVERY

        # Broadcast → expired
        broadcast_doc = db.collection("broadcasts").document(broadcast_id).get()
        assert broadcast_doc.to_dict()["status"] == "expired"

        # UI event emitted
        assert any(e.type == "broadcast_expired" for e in alice_state.ui_events)

    def test_outgoing_offer_expired_with_broadcast_returns_to_broadcast_active(
        self, db
    ):
        """If sender had active broadcast when offer expired, they return to BROADCAST_ACTIVE."""
        alice_uid = "alice_offer_expire_has_broadcast"
        bob_uid = "bob_offer_expire_has_broadcast"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        # Alice broadcasts first
        service.create_broadcast(alice_uid, make_broadcast_request())

        # Alice sends offer to Bob (now in OUTGOING_OFFER_PENDING but retains broadcast)
        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        # Manually expire the offer
        db.collection("offers").document(offer_id).update(
            {"expiresAt": datetime.now(timezone.utc) - timedelta(minutes=1)}
        )

        # Alice's state read triggers freshness reconciliation
        alice_state = service.get_me_state(alice_uid)

        # Alice → BROADCAST_ACTIVE (not DISCOVERY, because activeBroadcastId exists)
        assert alice_state.mode == PlayTabStateEnum.BROADCAST_ACTIVE

    def test_non_expired_broadcast_stays_active(self, db):
        """A fresh broadcast does not trigger reconciliation."""
        alice_uid = "alice_fresh_broadcast"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        service.create_broadcast(alice_uid, make_broadcast_request(hours_from_now=2))
        alice_state = service.get_me_state(alice_uid)

        assert alice_state.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert alice_state.ui_events == []


# ===== Test: Error Handling =====


class TestErrorHandling:
    def test_accept_offer_not_recipient(self, db):
        """Charlie cannot accept an offer sent to Bob."""
        alice_uid = "alice_not_recipient"
        bob_uid = "bob_not_recipient"
        charlie_uid = "charlie_not_recipient"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, charlie_uid, "Charlie")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))

        with pytest.raises(ValueError, match="not the recipient"):
            service.accept_offer(charlie_uid, offer_resp.offer_id)

    def test_cancel_offer_not_sender(self, db):
        """Bob cannot cancel an offer Alice sent."""
        alice_uid = "alice_not_sender"
        bob_uid = "bob_not_sender"
        charlie_uid = "charlie_not_sender"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, charlie_uid, "Charlie")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))

        with pytest.raises(ValueError, match="not the sender"):
            service.cancel_offer(charlie_uid, offer_resp.offer_id)

    def test_accept_expired_offer(self, db):
        """Accepting an expired offer raises ValueError."""
        alice_uid = "alice_accept_expired"
        bob_uid = "bob_accept_expired"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        # Expire the offer manually
        db.collection("offers").document(offer_id).update(
            {"expiresAt": datetime.now(timezone.utc) - timedelta(minutes=1)}
        )

        with pytest.raises(ValueError, match="expired"):
            service.accept_offer(bob_uid, offer_id)

    def test_accept_already_accepted_offer(self, db):
        """Accepting an offer a second time raises ValueError."""
        alice_uid = "alice_double_accept"
        bob_uid = "bob_double_accept"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        service.accept_offer(bob_uid, offer_resp.offer_id)

        with pytest.raises(ValueError):
            service.accept_offer(bob_uid, offer_resp.offer_id)

    def test_cancel_broadcast_no_active_broadcast(self, db):
        """cancel_broadcast on DISCOVERY user raises ValueError."""
        alice_uid = "alice_no_broadcast_cancel"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        with pytest.raises(ValueError, match="No active broadcast"):
            service.cancel_broadcast(alice_uid)

    def test_send_offer_sender_already_has_outgoing(self, db):
        """Sender with an active outgoing offer cannot send another."""
        alice_uid = "alice_already_has_outgoing"
        bob_uid = "bob_already_has_outgoing"
        charlie_uid = "charlie_already_has_outgoing"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, charlie_uid, "Charlie")
        service = make_play_service(db)

        service.send_offer(alice_uid, make_offer_request(bob_uid))

        with pytest.raises(ValueError, match="active outgoing offer"):
            service.send_offer(alice_uid, make_offer_request(charlie_uid))

    def test_accept_offer_not_found(self, db):
        """Accepting a non-existent offer raises ValueError."""
        alice_uid = "alice_accept_nonexistent"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        with pytest.raises(ValueError, match="not found"):
            service.accept_offer(alice_uid, "nonexistent_offer_id")


# ===== Test: Concurrent Race Condition =====


class TestConcurrentRace:
    def test_concurrent_offer_accept_race(self, db):
        """
        Two concurrent accept calls for the same offer.

        The second should fail because the offer is no longer pending.
        Note: Since the status check occurs outside the Firestore transaction,
        sequential serialization of these calls is not guaranteed under extreme
        concurrency. This test documents expected behavior under typical load.
        """
        alice_uid = "alice_race"
        bob_uid = "bob_race"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        successes = []
        failures = []

        def try_accept():
            try:
                result = service.accept_offer(bob_uid, offer_id)
                successes.append(result)
            except ValueError as e:
                failures.append(e)

        # Two threads attempt to accept the same offer
        t1 = threading.Thread(target=try_accept)
        t2 = threading.Thread(target=try_accept)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # At least one succeeded
        assert len(successes) >= 1, "At least one accept should succeed"
        # Total outcomes account for both threads
        assert len(successes) + len(failures) == 2

        # The offer must be in a terminal state (accepted)
        offer_doc = db.collection("offers").document(offer_id).get()
        assert offer_doc.to_dict()["status"] == "accepted"

    def test_broadcast_accept_race_different_offers(self, db):
        """
        Alice has two pending offers. Bob and Charlie's accepts run concurrently.
        Only one match should be created; Alice should end up MATCH_SCHEDULED.
        """
        alice_uid = "alice_queue_race"
        bob_uid = "bob_queue_race"
        charlie_uid = "charlie_queue_race"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, charlie_uid, "Charlie")
        service = make_play_service(db)

        service.create_broadcast(alice_uid, make_broadcast_request())
        bob_offer = service.send_offer(bob_uid, make_offer_request(alice_uid))
        charlie_offer = service.send_offer(charlie_uid, make_offer_request(alice_uid))

        successes = []
        failures = []

        def accept_bob():
            try:
                successes.append(service.accept_offer(alice_uid, bob_offer.offer_id))
            except Exception as e:
                failures.append(("bob", e))

        def accept_charlie():
            try:
                successes.append(
                    service.accept_offer(alice_uid, charlie_offer.offer_id)
                )
            except Exception as e:
                failures.append(("charlie", e))

        t1 = threading.Thread(target=accept_bob)
        t2 = threading.Thread(target=accept_charlie)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Alice must be in a consistent state
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "MATCH_SCHEDULED"


# ===== Test: Time-Based Edge Cases =====


class TestTimeBasedEdgeCases:
    def test_expires_at_exactly_now_rejected(self, db):
        """expiresAt == now is treated as not in future (uses strict < check)."""
        alice_uid = "alice_expires_now"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        now = datetime.now(timezone.utc)
        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            expires_at=now,  # exactly now — not in the future
            location=BroadcastLocation(area=10001),
        )

        with pytest.raises(ValueError, match="future"):
            service.create_broadcast(alice_uid, request)

    def test_expires_at_one_second_future_accepted(self, db):
        """expiresAt = now + 1s is a valid future time and the broadcast is created."""
        alice_uid = "alice_expires_1s"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            location=BroadcastLocation(area=10001),
        )

        response = service.create_broadcast(alice_uid, request)
        assert response.broadcast_id

    def test_naive_datetime_coerced_to_utc(self, db):
        """
        GsmBaseModel._ensure_aware_datetime coerces naive datetimes to UTC,
        so a naive expiresAt is accepted rather than raising TypeError.
        Naive datetime + 2h is a valid future time after coercion.
        """
        alice_uid = "alice_naive_dt"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        import datetime as dt_module

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            expires_at=dt_module.datetime.now() + dt_module.timedelta(hours=2),  # naive
            location=BroadcastLocation(area=10001),
        )

        # Coerced to UTC by GsmBaseModel — broadcast is created successfully
        response = service.create_broadcast(alice_uid, request)
        assert response.broadcast_id
        assert (
            response.expires_at.tzinfo is not None
        )  # confirmed UTC-aware after coercion


# ===== Test: State Machine Edge Cases =====


class TestStateMachineEdgeCases:
    def test_broadcast_from_incoming_offer_pending(self, db):
        """User in INCOMING_OFFER_PENDING cannot create a broadcast."""
        alice_uid = "alice_incoming_no_broadcast"
        bob_uid = "bob_incoming_no_broadcast"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        # Bob sends offer to Alice → Alice enters INCOMING_OFFER_PENDING
        service.send_offer(bob_uid, make_offer_request(alice_uid))

        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "INCOMING_OFFER_PENDING"

        with pytest.raises(ValueError, match="INCOMING_OFFER_PENDING"):
            service.create_broadcast(alice_uid, make_broadcast_request())

    def test_broadcast_from_outgoing_offer_pending(self, db):
        """User in OUTGOING_OFFER_PENDING cannot create a broadcast."""
        alice_uid = "alice_outgoing_no_broadcast"
        bob_uid = "bob_outgoing_no_broadcast"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        # Alice sends offer to Bob → Alice enters OUTGOING_OFFER_PENDING
        service.send_offer(alice_uid, make_offer_request(bob_uid))

        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "OUTGOING_OFFER_PENDING"

        with pytest.raises(ValueError, match="OUTGOING_OFFER_PENDING"):
            service.create_broadcast(alice_uid, make_broadcast_request())

    def test_send_offer_to_self(self, db):
        """
        Sending an offer to yourself has no explicit validation.
        Documents current behavior: the operation completes because both
        sender and recipient lookups find the same user doc. The resulting
        Firestore state is inconsistent (both outgoing and incoming fields set),
        but no error is raised.
        """
        alice_uid = "alice_self_offer"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        # No ValueError raised — no self-offer guard exists
        offer_resp = service.send_offer(alice_uid, make_offer_request(alice_uid))
        assert offer_resp.offer_id

        # Offer doc is created with fromUid == toUid
        offer_doc = db.collection("offers").document(offer_resp.offer_id).get()
        data = offer_doc.to_dict()
        assert data["fromUid"] == alice_uid
        assert data["toUid"] == alice_uid

    def test_accept_own_offer(self, db):
        """Sender cannot accept their own outgoing offer (not the recipient)."""
        alice_uid = "alice_accept_own"
        bob_uid = "bob_accept_own"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))

        with pytest.raises(ValueError, match="not the recipient"):
            service.accept_offer(alice_uid, offer_resp.offer_id)

    def test_decline_after_accept(self, db):
        """Declining an already-accepted offer raises ValueError."""
        alice_uid = "alice_decline_after_accept"
        bob_uid = "bob_decline_after_accept"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        service.accept_offer(bob_uid, offer_resp.offer_id)

        with pytest.raises(ValueError):
            service.decline_offer(bob_uid, offer_resp.offer_id)

    def test_cancel_after_accept(self, db):
        """Sender cannot cancel an already-accepted offer."""
        alice_uid = "alice_cancel_after_accept"
        bob_uid = "bob_cancel_after_accept"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        service.accept_offer(bob_uid, offer_resp.offer_id)

        with pytest.raises(ValueError):
            service.cancel_offer(alice_uid, offer_resp.offer_id)

    def test_match_scheduled_user_cannot_send_offer(self, db):
        """User in MATCH_SCHEDULED state cannot send a new offer."""
        alice_uid = "alice_match_no_offer"
        bob_uid = "bob_match_no_offer"
        charlie_uid = "charlie_match_no_offer"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        seed_discovery_user(db, charlie_uid, "Charlie")
        service = make_play_service(db)

        # Alice and Bob reach MATCH_SCHEDULED
        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        service.accept_offer(bob_uid, offer_resp.offer_id)

        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "MATCH_SCHEDULED"

        with pytest.raises(ValueError, match="MATCH_SCHEDULED"):
            service.send_offer(alice_uid, make_offer_request(charlie_uid))


# ===== Test: Offer Queue Edge Cases =====


class TestOfferQueueEdgeCases:
    def test_large_queue_accepting_one_declines_rest(self, db):
        """
        User receives 5 pending offers.
        Accepting one declines all 4 others atomically.
        """
        alice_uid = "alice_large_queue"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        service.create_broadcast(alice_uid, make_broadcast_request())

        # 5 senders each queue an offer for Alice
        senders = []
        offer_ids = []
        for i in range(5):
            uid = f"sender_large_{i}"
            seed_discovery_user(db, uid, f"Sender{i}")
            senders.append(uid)
            resp = service.send_offer(uid, make_offer_request(alice_uid))
            offer_ids.append(resp.offer_id)

        alice_tab = get_play_tab(db, alice_uid)
        assert len(alice_tab["pendingIncomingOfferIds"]) == 5

        # Alice accepts the third offer
        service.accept_offer(alice_uid, offer_ids[2])

        # Accepted offer is accepted
        accepted_doc = db.collection("offers").document(offer_ids[2]).get()
        assert accepted_doc.to_dict()["status"] == "accepted"

        # All other 4 offers are declined
        for i, offer_id in enumerate(offer_ids):
            if i == 2:
                continue
            doc = db.collection("offers").document(offer_id).get()
            assert doc.to_dict()["status"] == "declined", (
                f"offer_ids[{i}] should be declined"
            )

        # Alice → MATCH_SCHEDULED, pending list cleared
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "MATCH_SCHEDULED"
        assert alice_tab.get("pendingIncomingOfferIds") == []

    def test_get_me_state_with_stale_offer_ids(self, db):
        """
        pendingIncomingOfferIds pointing to deleted/non-existent docs
        do not crash get_me_state. get_by_ids silently skips missing docs.
        """
        alice_uid = "alice_stale_offer_ids"
        broadcast_id = "broadcast_stale_test"
        now = datetime.now(timezone.utc)

        # Seed user in BROADCAST_ACTIVE with stale offer IDs
        db.collection("users").document(alice_uid).set(
            {
                "name": "Alice",
                "email": "alice@test.com",
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": broadcast_id,
                    "pendingIncomingOfferIds": ["nonexistent_1", "nonexistent_2"],
                    "updatedAt": now,
                },
            }
        )

        # Seed the broadcast doc so the service can fetch it
        db.collection("broadcasts").document(broadcast_id).set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "tennis",
                "availability": "today",
                "courtStatus": "have_court",
                "status": "active",
                "expiresAt": now + timedelta(hours=2),
                "createdAt": now,
                "location": {"area": 10001},
            }
        )

        service = make_play_service(db)
        state = service.get_me_state(alice_uid)

        # No crash — returns BROADCAST_ACTIVE with empty pending offers list
        assert state.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert state.ui_events == []

    def test_get_me_state_broadcast_active_empty_pending_list(self, db):
        """BROADCAST_ACTIVE user with empty pendingIncomingOfferIds returns correct state."""
        alice_uid = "alice_empty_pending"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        service.create_broadcast(alice_uid, make_broadcast_request())

        state = service.get_me_state(alice_uid)

        assert state.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert state.ui_events == []

    def test_declining_reduces_pending_list(self, db):
        """
        Recipient with 3 pending offers declines one; list reduces to 2
        and state stays INCOMING_OFFER_PENDING.
        """
        alice_uid = "alice_decline_one_of_three"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        offer_ids = []
        for i in range(3):
            uid = f"sender_decline_{i}"
            seed_discovery_user(db, uid, f"Sender{i}")
            resp = service.send_offer(uid, make_offer_request(alice_uid))
            offer_ids.append(resp.offer_id)

        alice_tab = get_play_tab(db, alice_uid)
        assert len(alice_tab["pendingIncomingOfferIds"]) == 3

        # Alice declines the first offer
        service.decline_offer(alice_uid, offer_ids[0])

        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "INCOMING_OFFER_PENDING"
        assert len(alice_tab["pendingIncomingOfferIds"]) == 2
        assert offer_ids[0] not in alice_tab["pendingIncomingOfferIds"]


# ===== Test: Data Validation Edge Cases =====


class TestDataValidationEdgeCases:
    def test_broadcast_active_state_includes_venue_ref(self, db):
        alice_uid = "alice_broadcast_state_venue_ref"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)
        venue_ref = VenueRef(
            venue_id="ten_twenty_club",
            place_id=None,
            name="Ten Twenty Club",
            coordinates=GeoCoordinates(lat=37.8362, lng=23.7627),
        )

        service.create_broadcast(alice_uid, make_broadcast_request(venue_ref=venue_ref))

        response = service.get_me_state(alice_uid)

        assert response.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert response.payload["venue_ref"]["venueId"] == "ten_twenty_club"
        assert response.payload["venue_ref"]["name"] == "Ten Twenty Club"

    def test_need_court_broadcast_ignores_venue_ref(self, db):
        alice_uid = "alice_need_court_venue_ignored"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)
        venue_ref = VenueRef(
            venue_id="ten_twenty_club",
            place_id=None,
            name="Ten Twenty Club",
            coordinates=GeoCoordinates(lat=37.8362, lng=23.7627),
        )

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location=None,
            venue_ref=venue_ref,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            location=BroadcastLocation(area=10001),
        )

        response = service.create_broadcast(alice_uid, request)
        broadcast_doc = (
            db.collection("broadcasts").document(response.broadcast_id).get()
        )

        assert broadcast_doc.to_dict()["venueRef"] is None

        state = service.get_me_state(alice_uid)
        assert state.payload["venue_ref"] is None

    def test_broadcast_location_area_only(self, db):
        """Broadcast with only area set (no geo) is valid."""
        alice_uid = "alice_area_only"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            location=BroadcastLocation(area=10001, geo=None, radius_km=None),
        )

        response = service.create_broadcast(alice_uid, request)
        assert response.broadcast_id

        doc = db.collection("broadcasts").document(response.broadcast_id).get()
        assert doc.to_dict()["location"]["area"] == 10001
        assert doc.to_dict()["location"]["geo"] is None

    def test_broadcast_location_geo_only(self, db):
        """Broadcast with only geo set (no area) is valid."""
        alice_uid = "alice_geo_only"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            location=BroadcastLocation(
                area=None,
                geo=GeoLocation(lat=40.7128, lng=-74.0060),
                radius_km=5.0,
            ),
        )

        response = service.create_broadcast(alice_uid, request)
        assert response.broadcast_id

        doc = db.collection("broadcasts").document(response.broadcast_id).get()
        assert doc.to_dict()["location"]["area"] is None
        assert doc.to_dict()["location"]["geo"]["lat"] == 40.7128

    def test_broadcast_location_both_none_currently_allowed(self, db):
        """
        Broadcast with neither area nor geo is currently allowed (no validation).
        Documents current behavior — product may add validation later.
        """
        alice_uid = "alice_no_location"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            location=BroadcastLocation(area=None, geo=None, radius_km=None),
        )

        # No ValueError — passes through without location validation
        response = service.create_broadcast(alice_uid, request)
        assert response.broadcast_id

    def test_offer_proposed_time_in_past_currently_allowed(self, db):
        """
        proposedTime in the past is currently allowed (no validation).
        Documents current behavior — product may add validation later.
        """
        alice_uid = "alice_past_proposed"
        bob_uid = "bob_past_proposed"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        request = SendOfferRequest(
            to_uid=bob_uid,
            sport=SportEnum.TENNIS,
            proposed_time=past_time,
        )

        # No ValueError — past proposed time is not validated
        offer_resp = service.send_offer(alice_uid, request)
        assert offer_resp.offer_id

    def test_offer_message_large_currently_allowed(self, db):
        """
        Very long offer messages have no max-length enforcement currently.
        Documents current behavior — product may add Pydantic max_length later.
        """
        alice_uid = "alice_long_message"
        bob_uid = "bob_long_message"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        request = SendOfferRequest(
            to_uid=bob_uid,
            sport=SportEnum.TENNIS,
            proposed_time=datetime.now(timezone.utc) + timedelta(hours=2),
            message="x" * 10_000,
        )

        offer_resp = service.send_offer(alice_uid, request)
        assert offer_resp.offer_id

        doc = db.collection("offers").document(offer_resp.offer_id).get()
        assert len(doc.to_dict()["message"]) == 10_000


# ===== Test: Concurrent Broadcast Creation =====


class TestConcurrentBroadcastCreation:
    def test_concurrent_broadcast_creation_same_user(self, db):
        """
        Two concurrent create_broadcast calls for the same DISCOVERY user.

        The service state check occurs outside the transaction, so both requests
        may read DISCOVERY and proceed. The Firestore transaction itself does not
        re-read the user doc to detect conflicts, meaning both may commit.
        This test documents the current behavior and flags the race condition.
        """
        alice_uid = "alice_concurrent_broadcast"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        successes = []
        failures = []

        def try_create():
            try:
                resp = service.create_broadcast(alice_uid, make_broadcast_request())
                successes.append(resp.broadcast_id)
            except ValueError as e:
                failures.append(e)

        t1 = threading.Thread(target=try_create)
        t2 = threading.Thread(target=try_create)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # At least one must succeed
        assert len(successes) >= 1

        # Alice's play tab must be in a consistent active state
        alice_tab = get_play_tab(db, alice_uid)
        assert alice_tab["state"] == "BROADCAST_ACTIVE"

    def test_race_sender_cancels_while_recipient_accepts(self, db):
        """
        Alice sends offer to Bob. Alice cancels while Bob simultaneously accepts.
        One operation wins; the other gets a ValueError (offer not pending).
        """
        alice_uid = "alice_cancel_race"
        bob_uid = "bob_cancel_race"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        offer_resp = service.send_offer(alice_uid, make_offer_request(bob_uid))
        offer_id = offer_resp.offer_id

        outcomes = []

        def alice_cancels():
            try:
                service.cancel_offer(alice_uid, offer_id)
                outcomes.append("cancelled")
            except ValueError:
                outcomes.append("cancel_failed")

        def bob_accepts():
            try:
                service.accept_offer(bob_uid, offer_id)
                outcomes.append("accepted")
            except ValueError:
                outcomes.append("accept_failed")

        t1 = threading.Thread(target=alice_cancels)
        t2 = threading.Thread(target=bob_accepts)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(outcomes) == 2

        # The offer must be in a terminal state
        offer_doc = db.collection("offers").document(offer_id).get()
        assert offer_doc.to_dict()["status"] in ("cancelled", "accepted")

    def test_race_broadcast_create_and_cancel(self, db):
        """
        Alice's create_broadcast and cancel_broadcast run concurrently.

        Possible outcomes depending on scheduling:
        - Cancel runs first → ValueError (no active broadcast), create succeeds
          → Alice ends up BROADCAST_ACTIVE
        - Create runs first, cancel also succeeds → Alice ends up DISCOVERY

        Either way, the final state must be internally consistent.
        """
        alice_uid = "alice_create_cancel_race"
        seed_discovery_user(db, alice_uid, "Alice")
        service = make_play_service(db)

        outcomes = []

        def try_create():
            try:
                resp = service.create_broadcast(alice_uid, make_broadcast_request())
                outcomes.append(("created", resp.broadcast_id))
            except ValueError:
                outcomes.append(("create_failed", None))

        def try_cancel():
            try:
                service.cancel_broadcast(alice_uid)
                outcomes.append(("cancelled", None))
            except ValueError:
                outcomes.append(("cancel_failed", None))

        t1 = threading.Thread(target=try_create)
        t2 = threading.Thread(target=try_cancel)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(outcomes) == 2

        alice_tab = get_play_tab(db, alice_uid)
        result_types = {o[0] for o in outcomes}

        if "cancelled" in result_types:
            # Create succeeded then cancel succeeded → DISCOVERY
            assert alice_tab["state"] == "DISCOVERY"
            assert alice_tab.get("activeBroadcastId") is None
        else:
            # Cancel failed (no broadcast yet) → create succeeded → BROADCAST_ACTIVE
            assert "created" in result_types
            assert alice_tab["state"] == "BROADCAST_ACTIVE"
            assert alice_tab.get("activeBroadcastId") is not None


# ===== Test: Discovery Feed =====


def seed_user_with_level(
    db,
    uid: str,
    name: str,
    padel_level: str | None = None,
    tennis_level: str | None = None,
) -> None:
    """Seed a user with sport-level preferences for discovery feed enrichment tests."""
    levels: dict[str, str] = {}
    if padel_level:
        levels["padel"] = padel_level
    if tennis_level:
        levels["tennis"] = tennis_level
    db.collection("users").document(uid).set(
        {
            "name": name,
            "email": f"{uid}@test.com",
            "preferences": {
                "area": 101,
                "levels": levels,
                "sports": list(levels.keys()),
            },
            "playTab": {
                "state": "BROADCAST_ACTIVE",
                "updatedAt": datetime.now(timezone.utc),
            },
        }
    )


def seed_region_config(db) -> None:
    """Seed config/regions for area_name resolution tests."""
    db.collection("config").document("regions").set(
        {
            "mapping": {"101": "athens", "202": "thessaloniki"},
            "version": 1,
        }
    )


class TestDiscoveryFeed:
    def test_basic_feed_returns_active_broadcasts(self, db):
        """build_discovery_feed returns broadcasts owned by others, not by caller."""
        alice_uid = "df_alice_basic"
        bob_uid = "df_bob_basic"
        caller_uid = "df_caller_basic"
        seed_user_with_level(db, alice_uid, "Alice", padel_level="advanced")
        seed_user_with_level(db, bob_uid, "Bob", padel_level="intermediate")
        seed_discovery_user(db, caller_uid, "Caller")

        service = make_play_service(db)

        now = datetime.now(timezone.utc)
        # Alice broadcasts HAVE_COURT padel
        db.collection("broadcasts").document("df_bc_alice").set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "have_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )
        # Bob broadcasts NEED_COURT padel with area
        db.collection("broadcasts").document("df_bc_bob").set(
            {
                "ownerUid": bob_uid,
                "ownerName": "Bob",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "need_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now - timedelta(minutes=5),
                "location": {"area": 101},
            }
        )

        feed = service.build_discovery_feed(caller_uid)
        assert len(feed.intents) == 2
        owner_uids = {item.to_uid for item in feed.intents}
        assert alice_uid in owner_uids
        assert bob_uid in owner_uids
        assert caller_uid not in owner_uids

    def test_caller_own_broadcast_excluded(self, db):
        """Caller's own broadcast is not included in the feed."""
        caller_uid = "df_caller_exclude"
        seed_user_with_level(db, caller_uid, "Caller", padel_level="beginner")

        service = make_play_service(db)
        now = datetime.now(timezone.utc)
        db.collection("broadcasts").document("df_bc_caller_self").set(
            {
                "ownerUid": caller_uid,
                "ownerName": "Caller",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "have_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )

        feed = service.build_discovery_feed(caller_uid)
        assert len(feed.intents) == 0

    def test_level_populated_from_owner_profile(self, db):
        """level field is resolved from owner's preferences.levels."""
        alice_uid = "df_alice_level"
        caller_uid = "df_caller_level"
        seed_user_with_level(db, alice_uid, "Alice", padel_level="advanced")
        seed_discovery_user(db, caller_uid, "Caller")
        seed_region_config(db)

        service = make_play_service(db)
        now = datetime.now(timezone.utc)
        db.collection("broadcasts").document("df_bc_level").set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "have_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )

        feed = service.build_discovery_feed(caller_uid)
        assert len(feed.intents) == 1
        assert feed.intents[0].level is not None
        assert feed.intents[0].level.value == "advanced"

    def test_venue_ref_only_on_have_court(self, db):
        """venue_ref is included for HAVE_COURT and omitted for NEED_COURT."""
        alice_uid = "df_alice_venue"
        caller_uid = "df_caller_venue"
        seed_user_with_level(db, alice_uid, "Alice", padel_level="intermediate")
        seed_discovery_user(db, caller_uid, "Caller")

        service = make_play_service(db)
        now = datetime.now(timezone.utc)
        db.collection("broadcasts").document("df_bc_have_court").set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "have_court",
                "venueRef": {
                    "venueId": "test_venue",
                    "placeId": None,
                    "name": "Test Club",
                    "coordinates": {"lat": 37.97, "lng": 23.72},
                },
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )

        feed = service.build_discovery_feed(caller_uid)
        assert len(feed.intents) == 1
        item = feed.intents[0]
        assert item.court_status.value == "have_court"
        assert item.venue_ref is not None
        assert item.venue_ref.name == "Test Club"

    def test_area_name_resolved_for_need_court(self, db):
        """area_name is resolved via region config for NEED_COURT broadcasts."""
        bob_uid = "df_bob_area"
        caller_uid = "df_caller_area"
        seed_user_with_level(db, bob_uid, "Bob", padel_level="beginner")
        seed_discovery_user(db, caller_uid, "Caller")
        seed_region_config(db)

        service = make_play_service(db)
        now = datetime.now(timezone.utc)
        db.collection("broadcasts").document("df_bc_need_court").set(
            {
                "ownerUid": bob_uid,
                "ownerName": "Bob",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "need_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )

        feed = service.build_discovery_feed(caller_uid)
        assert len(feed.intents) == 1
        item = feed.intents[0]
        assert item.court_status.value == "need_court"
        assert item.venue_ref is None
        assert item.area_name == "athens"

    def test_match_type_filter(self, db):
        """Passing match_type=doubles filters to only doubles broadcasts."""
        alice_uid = "df_alice_filter"
        bob_uid = "df_bob_filter"
        caller_uid = "df_caller_filter"
        seed_user_with_level(db, alice_uid, "Alice", padel_level="advanced")
        seed_user_with_level(db, bob_uid, "Bob", padel_level="advanced")
        seed_discovery_user(db, caller_uid, "Caller")

        service = make_play_service(db)
        now = datetime.now(timezone.utc)
        # Alice: singles
        db.collection("broadcasts").document("df_bc_singles").set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "have_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )
        # Bob: doubles
        db.collection("broadcasts").document("df_bc_doubles").set(
            {
                "ownerUid": bob_uid,
                "ownerName": "Bob",
                "sport": "padel",
                "matchType": "doubles",
                "broadcastType": "find_fourth",
                "availability": "today",
                "courtStatus": "have_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )

        feed = service.build_discovery_feed(
            caller_uid, match_type=MatchTypeEnum.DOUBLES
        )
        assert len(feed.intents) == 1
        assert feed.intents[0].to_uid == bob_uid

    def test_active_clubs_nearby_distinct_areas(self, db):
        """active_clubs_nearby counts distinct location areas."""
        alice_uid = "df_alice_areas"
        bob_uid = "df_bob_areas"
        caller_uid = "df_caller_areas"
        seed_user_with_level(db, alice_uid, "Alice", padel_level="advanced")
        seed_user_with_level(db, bob_uid, "Bob", padel_level="intermediate")
        seed_discovery_user(db, caller_uid, "Caller")
        seed_region_config(db)

        service = make_play_service(db)
        now = datetime.now(timezone.utc)
        # Alice in area 101, Bob in area 202 — two distinct areas
        db.collection("broadcasts").document("df_bc_area101").set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "need_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )
        db.collection("broadcasts").document("df_bc_area202").set(
            {
                "ownerUid": bob_uid,
                "ownerName": "Bob",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "need_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now - timedelta(minutes=1),
                "location": {"area": 202},
            }
        )

        feed = service.build_discovery_feed(caller_uid)
        # 2 distinct areas
        assert feed.active_clubs_nearby == 2

    def test_region_config_missing_fallback(self, db):
        """When config/regions doc is absent, area_name falls back to None."""
        alice_uid = "df_alice_no_config"
        caller_uid = "df_caller_no_config"
        seed_user_with_level(db, alice_uid, "Alice", padel_level="beginner")
        seed_discovery_user(db, caller_uid, "Caller")
        # do NOT seed config/regions

        service = make_play_service(db)
        now = datetime.now(timezone.utc)
        db.collection("broadcasts").document("df_bc_no_config").set(
            {
                "ownerUid": alice_uid,
                "ownerName": "Alice",
                "sport": "padel",
                "matchType": "singles",
                "broadcastType": "find_opponent",
                "availability": "today",
                "courtStatus": "need_court",
                "status": "active",
                "expiresAt": now + timedelta(days=1),
                "createdAt": now,
                "location": {"area": 101},
            }
        )

        import app.repos.region_config_repo as rc_module

        db.collection("config").document("regions").delete()
        rc_module._cache = None  # clear TTL cache so the miss is fresh
        feed = service.build_discovery_feed(caller_uid)
        assert len(feed.intents) == 1
        assert feed.intents[0].area_name is None
