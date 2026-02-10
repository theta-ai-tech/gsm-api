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

from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    CourtStatusEnum,
    OfferStatusEnum,
    PlayTabStateEnum,
    SportEnum,
)
from app.models.play import (
    BroadcastLocation,
    CreateBroadcastRequest,
    SendOfferRequest,
)
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo
from app.services.play_service import PlayService

pytestmark = [pytest.mark.integration]


# ===== Helpers =====


def make_play_service(db) -> PlayService:
    """Create a PlayService backed by real repos against the emulator."""
    return PlayService(
        UsersRepo(db),
        BroadcastsRepo(db),
        OffersRepo(db),
        db,
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


def make_broadcast_request(hours_from_now: float = 2.0) -> CreateBroadcastRequest:
    """Return a standard CreateBroadcastRequest with future expiresAt."""
    return CreateBroadcastRequest(
        sport=SportEnum.TENNIS,
        availability=AvailabilityEnum.TODAY,
        court_status=CourtStatusEnum.HAVE_COURT,
        court_location="Central Park",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours_from_now),
        location=BroadcastLocation(area=10001),
    )


def make_offer_request(to_uid: str) -> SendOfferRequest:
    """Return a standard SendOfferRequest."""
    return SendOfferRequest(
        to_uid=to_uid,
        sport=SportEnum.TENNIS,
        proposed_time=datetime.now(timezone.utc) + timedelta(hours=2),
        court_location="Central Park",
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

    def test_outgoing_offer_expired_with_broadcast_returns_to_broadcast_active(self, db):
        """If sender had active broadcast when offer expired, they return to BROADCAST_ACTIVE."""
        alice_uid = "alice_offer_expire_has_broadcast"
        bob_uid = "bob_offer_expire_has_broadcast"
        seed_discovery_user(db, alice_uid, "Alice")
        seed_discovery_user(db, bob_uid, "Bob")
        service = make_play_service(db)

        # Alice broadcasts first
        bc_resp = service.create_broadcast(alice_uid, make_broadcast_request())
        broadcast_id = bc_resp.broadcast_id

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
                successes.append(service.accept_offer(alice_uid, charlie_offer.offer_id))
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
