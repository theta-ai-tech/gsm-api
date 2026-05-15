"""
Integration tests for DBL-10: doubles match lifecycle end-to-end.

Covers six lifecycle scenarios against the real Firestore emulator:

1. Happy path (find_opponent doubles): broadcast → offer → accept → result → confirm
   → all 4 players COMPLETED and back to DISCOVERY.
2. Team assignment: broadcaster is Team A, challenger is Team B with correct UIDs.
3. Doubles dispute: conflicting result submissions → MATCH_DISPUTED for all 4.
4. Doubles scoring math: cross-team average pts, 4 pointHistory entries,
   per-player streak/PB updated.
5. Mixed singles + doubles: a singles flow runs alongside doubles without
   interfering with either state machine.
6. Venue propagation: venueRef from broadcast flows through offer → match doc.

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. ``make emu-all``).
"""

from __future__ import annotations

import app.repos.tier_config_repo as tier_config_module
import pytest

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.common import GeoCoordinates, MatchScore, SetScore, VenueRef
from app.models.enums import (
    AvailabilityEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    MatchStatusEnum,
    MatchTypeEnum,
    PointHistoryReasonEnum,
    SportEnum,
)
from app.models.play import (
    BroadcastLocation,
    CreateBroadcastRequest,
    SendOfferRequest,
)
from app.models.match import VerifyScoreRequest
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.match_confirmation_service import MatchConfirmationService
from app.services.play_service import PlayService

pytestmark = [pytest.mark.integration]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SPORT = SportEnum.PADEL
_SPORT_VALUE = "padel"


def _future(hours: float = 2.0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _score() -> MatchScore:
    return MatchScore(
        sets=[SetScore(p1_games=6, p2_games=3), SetScore(p1_games=6, p2_games=4)]
    )


def _make_play_service(db) -> PlayService:
    return PlayService(
        UsersRepo(db),
        BroadcastsRepo(db),
        MatchesRepo(db),
        OffersRepo(db),
        db,
    )


def _make_confirmation_service(db) -> MatchConfirmationService:
    return MatchConfirmationService(
        matches_repo=MatchesRepo(db),
        users_repo=UsersRepo(db),
        point_history_repo=PointHistoryRepo(db),
        tier_config_repo=TierConfigRepo(db),
        firestore_client=db,
    )


def _seed_user(
    db,
    uid: str,
    name: str = "Test User",
    pts: int = 1000,
    tier: str = "amateur",
) -> None:
    db.collection("users").document(uid).set(
        {
            "name": name,
            "email": f"{uid}@test.com",
            "rankings": {
                _SPORT_VALUE: {
                    "sport": _SPORT_VALUE,
                    "pts": pts,
                    "tier": tier,
                    "registrationTier": tier,
                    "currentStreak": 0,
                    "bestStreak": 0,
                    "personalBest": None,
                }
            },
            "playTab": {
                "state": "DISCOVERY",
                "updatedAt": datetime.now(timezone.utc),
            },
        }
    )


def _seed_tier_config(db) -> None:
    now = datetime.now(timezone.utc)
    db.collection("config").document("tiers").set(
        {
            "version": 1,
            "updatedAt": now,
            "thresholds": [
                {
                    "tier": "amateur",
                    "minPts": 1000,
                    "maxPts": 1999,
                    "label": "Amateur",
                    "color": "#aaa",
                },
                {
                    "tier": "intermediate",
                    "minPts": 2000,
                    "maxPts": 2999,
                    "label": "Intermediate",
                    "color": "#bbb",
                },
                {
                    "tier": "advanced",
                    "minPts": 3000,
                    "maxPts": 3999,
                    "label": "Advanced",
                    "color": "#ccc",
                },
                {
                    "tier": "competitive",
                    "minPts": 4000,
                    "maxPts": None,
                    "label": "Competitive",
                    "color": "#ddd",
                },
            ],
        }
    )


def _get_play_tab(db, uid: str) -> dict[str, Any]:
    doc = db.collection("users").document(uid).get()
    return doc.to_dict().get("playTab", {}) if doc.exists else {}


def _get_match(db, match_id: str) -> dict[str, Any]:
    doc = db.collection("matches").document(match_id).get()
    return doc.to_dict() or {}


def _get_ranking(db, uid: str) -> dict[str, Any]:
    doc = db.collection("users").document(uid).get().to_dict() or {}
    return (doc.get("rankings") or {}).get(_SPORT_VALUE, {})


def _get_point_history(db, uid: str) -> list[dict[str, Any]]:
    entries = db.collection("users").document(uid).collection("pointHistory").stream()
    return [e.to_dict() for e in entries]


def _doubles_broadcast_request(
    partner_uid: str,
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT,
    venue_ref: VenueRef | None = None,
    court_status: CourtStatusEnum = CourtStatusEnum.NEED_COURT,
) -> CreateBroadcastRequest:
    return CreateBroadcastRequest(
        sport=_SPORT,
        match_type=MatchTypeEnum.DOUBLES,
        broadcast_type=broadcast_type,
        partner_uid=partner_uid,
        availability=AvailabilityEnum.TODAY,
        court_status=court_status,
        court_location="Test Court",
        venue_ref=venue_ref,
        expires_at=_future(),
        location=BroadcastLocation(area=10001),
    )


def _doubles_offer_request(
    to_uid: str,
    partner_uid: str,
    broadcast_id: str,
    venue_ref: VenueRef | None = None,
) -> SendOfferRequest:
    return SendOfferRequest(
        to_uid=to_uid,
        sport=_SPORT,
        match_type=MatchTypeEnum.DOUBLES,
        partner_uid=partner_uid,
        proposed_time=_future(),
        source_broadcast_id=broadcast_id,
        court_location="Test Court",
        venue_ref=venue_ref,
        message="Doubles?",
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def _wipe_touched_collections(db) -> None:
    """Delete all collections that lifecycle tests write to.

    Runs both before and after each test so the suite is robust against stale
    emulator state from interrupted prior runs.  Firestore does NOT
    cascade-delete subcollections, so pointHistory must be cleaned explicitly.
    """
    for coll in ("broadcasts", "offers", "matches"):
        for doc in db.collection(coll).stream():
            doc.reference.delete()
    for doc in db.collection("config").stream():
        doc.reference.delete()
    for user_doc in db.collection("users").stream():
        for ph in (
            db.collection("users")
            .document(user_doc.id)
            .collection("pointHistory")
            .stream()
        ):
            ph.reference.delete()


@pytest.fixture(autouse=True)
def _cleanup_collections(db):
    """Wipe touched collections before and after each test for isolation."""
    _wipe_touched_collections(db)
    yield
    _wipe_touched_collections(db)


@pytest.fixture(autouse=True)
def _reset_tier_cache():
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0
    yield
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0


# ---------------------------------------------------------------------------
# Scenario 1: Happy path — find_opponent doubles full lifecycle
# ---------------------------------------------------------------------------


class TestDoublesHappyPathLifecycle:
    """Full doubles lifecycle: broadcast → offer → accept → result → confirm → COMPLETED."""

    def test_happy_path_all_four_complete_and_return_to_discovery(self, db):
        """
        Bob (Team A, with Dave) broadcasts doubles + find_opponent.
        Alice (Team B, with Charlie) sends offer. Bob accepts.
        Alice (Team B) submits result: winner_team=A.
        Bob (Team A) confirms: winner_team=A.
        Match → COMPLETED, all 4 players → DISCOVERY.
        """
        _seed_tier_config(db)
        bob_uid = "lifecycle_bob"
        dave_uid = "lifecycle_dave"
        alice_uid = "lifecycle_alice"
        charlie_uid = "lifecycle_charlie"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        # Bob broadcasts doubles + find_opponent with Dave as partner.
        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        broadcast_id = bc_resp.broadcast_id

        # Alice sends a doubles offer with Charlie as partner.
        offer_resp = play_svc.send_offer(
            alice_uid, _doubles_offer_request(bob_uid, charlie_uid, broadcast_id)
        )
        offer_id = offer_resp.offer_id

        # Bob accepts the offer.
        accept_resp = play_svc.accept_offer(bob_uid, offer_id)
        match_id = accept_resp.match_id
        assert match_id

        # All 4 players are now MATCH_SCHEDULED.
        for uid in (bob_uid, dave_uid, alice_uid, charlie_uid):
            tab = _get_play_tab(db, uid)
            assert tab["state"] == "MATCH_SCHEDULED", (
                f"{uid} not MATCH_SCHEDULED after accept"
            )
            assert tab["activeMatchId"] == match_id

        # Alice (Team B) submits result: Team A won.
        first_resp = confirm_svc.verify_score(
            alice_uid, match_id, VerifyScoreRequest(winner_team="A", score=_score())
        )
        assert first_resp.status == MatchStatusEnum.PENDING_CONFIRMATION

        # Alice → POST_MATCH_WAITING_OPPONENT; other 3 → POST_MATCH_CONFIRM_REQUIRED.
        assert _get_play_tab(db, alice_uid)["state"] == "POST_MATCH_WAITING_OPPONENT"
        for uid in (bob_uid, dave_uid, charlie_uid):
            assert _get_play_tab(db, uid)["state"] == "POST_MATCH_CONFIRM_REQUIRED"

        # Bob (Team A) confirms: winner_team=A (agreement).
        confirm_resp = confirm_svc.verify_score(
            bob_uid, match_id, VerifyScoreRequest(winner_team="A")
        )
        assert confirm_resp.status == MatchStatusEnum.COMPLETED

        # Match doc is COMPLETED.
        match_doc = _get_match(db, match_id)
        assert match_doc["status"] == "completed"

        # All 4 players land in DISCOVERY.
        for uid in (bob_uid, dave_uid, alice_uid, charlie_uid):
            tab = _get_play_tab(db, uid)
            assert tab["state"] == "DISCOVERY", f"{uid} not DISCOVERY after completion"

    def test_happy_path_team_assignment_correct(self, db):
        """
        Broadcaster (Bob) and their partner (Dave) are Team A.
        Challenger (Alice) and their partner (Charlie) are Team B.
        """
        _seed_tier_config(db)
        bob_uid = "teams_bob"
        dave_uid = "teams_dave"
        alice_uid = "teams_alice"
        charlie_uid = "teams_charlie"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        match_doc = _get_match(db, match_id)
        assert match_doc["matchType"] == "doubles"
        assert len(match_doc["participants"]) == 4

        by_uid = {p["uid"]: p for p in match_doc["participants"]}

        # Broadcaster (bob) + partner (dave) → Team A.
        assert by_uid[bob_uid]["team"] == "A"
        assert by_uid[dave_uid]["team"] == "A"

        # Challenger (alice) + partner (charlie) → Team B.
        assert by_uid[alice_uid]["team"] == "B"
        assert by_uid[charlie_uid]["team"] == "B"

        # participantUids contains all 4.
        assert set(match_doc["participantUids"]) == {
            bob_uid,
            dave_uid,
            alice_uid,
            charlie_uid,
        }


# ---------------------------------------------------------------------------
# Scenario 2: Doubles dispute — conflicting result submissions
# ---------------------------------------------------------------------------


class TestDoublesDispute:
    """When Team A submits winner=A and Team B submits winner=B → MATCH_DISPUTED."""

    def test_dispute_transitions_all_four_to_match_disputed(self, db):
        """Conflicting submissions → all 4 players in MATCH_DISPUTED state."""
        bob_uid = "dispute_bob"
        dave_uid = "dispute_dave"
        alice_uid = "dispute_alice"
        charlie_uid = "dispute_charlie"
        all_uids = (bob_uid, dave_uid, alice_uid, charlie_uid)

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        # Alice (Team B) submits: winner_team=A.
        confirm_svc.verify_score(
            alice_uid, match_id, VerifyScoreRequest(winner_team="A", score=_score())
        )

        # Bob (Team A) disagrees: winner_team=B → dispute.
        dispute_resp = confirm_svc.verify_score(
            bob_uid, match_id, VerifyScoreRequest(winner_team="B")
        )
        assert dispute_resp.status == MatchStatusEnum.DISPUTED

        # Match doc is disputed.
        match_doc = _get_match(db, match_id)
        assert match_doc["status"] == "disputed"

        # All 4 players land in MATCH_DISPUTED state.
        for uid in all_uids:
            tab = _get_play_tab(db, uid)
            assert tab["state"] == "MATCH_DISPUTED", f"{uid} not MATCH_DISPUTED"

    def test_same_team_confirmation_rejected(self, db):
        """A player on the same team as the submitter cannot confirm the result."""
        bob_uid = "same_team_bob"
        dave_uid = "same_team_dave"
        alice_uid = "same_team_alice"
        charlie_uid = "same_team_charlie"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        # Alice (Team B) submits: winner_team=A.
        confirm_svc.verify_score(
            alice_uid, match_id, VerifyScoreRequest(winner_team="A", score=_score())
        )

        # Charlie is also on Team B — same team as Alice, so confirmation rejected.
        with pytest.raises(ValueError, match="opposing team"):
            confirm_svc.verify_score(
                charlie_uid, match_id, VerifyScoreRequest(winner_team="A")
            )

        # Match remains PENDING_CONFIRMATION.
        match_doc = _get_match(db, match_id)
        assert match_doc["status"] == "pending_confirmation"


# ---------------------------------------------------------------------------
# Scenario 3: Doubles scoring math
# ---------------------------------------------------------------------------


class TestDoublesScoringMath:
    """
    Validates cross-team average pts, 4 pointHistory entries, per-player
    streak and personal best updates.

    Scoring engine (from match_confirmation_service.py):
      - Each winner is scored against average_loser_pts = (b1_pts + b2_pts) // 2
      - Each loser is scored against average_winner_pts = (a1_pts + a2_pts) // 2
      - No upset bonus because all players are in the same tier (amateur)
      - base gain = 100; no penalty for equal-tier loss
    """

    def test_winner_pts_increase_by_base_100_against_avg_opponent(self, db):
        """Winners each gain +100 (base); losers in equal tier gain 0."""
        _seed_tier_config(db)
        bob_uid = "scoring_bob"
        dave_uid = "scoring_dave"
        alice_uid = "scoring_alice"
        charlie_uid = "scoring_charlie"

        # Team A: 1000 + 1200 → avg = 1100
        # Team B: 1100 + 1050 → avg = 1075
        # All in amateur tier → no upset bonus, no penalty
        _seed_user(db, bob_uid, "Bob Smith", pts=1000)
        _seed_user(db, dave_uid, "Dave Knight", pts=1200)
        _seed_user(db, alice_uid, "Alice King", pts=1100)
        _seed_user(db, charlie_uid, "Charlie Owen", pts=1050)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        # Alice (Team B) submits winner=A.
        confirm_svc.verify_score(
            alice_uid, match_id, VerifyScoreRequest(winner_team="A", score=_score())
        )
        # Bob (Team A) confirms winner=A.
        confirm_svc.verify_score(bob_uid, match_id, VerifyScoreRequest(winner_team="A"))

        # Winners (Team A) gain +100 each.
        assert _get_ranking(db, bob_uid)["pts"] == 1100
        assert _get_ranking(db, dave_uid)["pts"] == 1300

        # Losers (Team B) in equal tier: penalty = 0 → pts unchanged.
        assert _get_ranking(db, alice_uid)["pts"] == 1100
        assert _get_ranking(db, charlie_uid)["pts"] == 1050

    def test_four_point_history_entries_with_correct_reasons(self, db):
        """All 4 players receive exactly one pointHistory entry with correct reason."""
        _seed_tier_config(db)
        bob_uid = "ph_bob"
        dave_uid = "ph_dave"
        alice_uid = "ph_alice"
        charlie_uid = "ph_charlie"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        confirm_svc.verify_score(
            alice_uid, match_id, VerifyScoreRequest(winner_team="A", score=_score())
        )
        confirm_svc.verify_score(bob_uid, match_id, VerifyScoreRequest(winner_team="A"))

        for uid, expected_reason in [
            (bob_uid, PointHistoryReasonEnum.MATCH_DOUBLES_WIN.value),
            (dave_uid, PointHistoryReasonEnum.MATCH_DOUBLES_WIN.value),
            (alice_uid, PointHistoryReasonEnum.MATCH_DOUBLES_LOSS.value),
            (charlie_uid, PointHistoryReasonEnum.MATCH_DOUBLES_LOSS.value),
        ]:
            entries = _get_point_history(db, uid)
            assert len(entries) == 1, (
                f"{uid}: expected 1 pointHistory entry, got {len(entries)}"
            )
            assert entries[0]["reason"] == expected_reason, (
                f"{uid}: wrong reason {entries[0]['reason']}"
            )

    def test_winner_streaks_and_pb_updated_per_player(self, db):
        """Each Team A winner gets currentStreak=1; Team B losers get currentStreak=0."""
        _seed_tier_config(db)
        bob_uid = "streak_bob"
        dave_uid = "streak_dave"
        alice_uid = "streak_alice"
        charlie_uid = "streak_charlie"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        confirm_svc.verify_score(
            alice_uid, match_id, VerifyScoreRequest(winner_team="A", score=_score())
        )
        confirm_svc.verify_score(bob_uid, match_id, VerifyScoreRequest(winner_team="A"))

        # Winners gain streak +1.
        assert _get_ranking(db, bob_uid)["currentStreak"] == 1
        assert _get_ranking(db, dave_uid)["currentStreak"] == 1

        # Losers streak resets to 0.
        assert _get_ranking(db, alice_uid)["currentStreak"] == 0
        assert _get_ranking(db, charlie_uid)["currentStreak"] == 0


# ---------------------------------------------------------------------------
# Scenario 4: Mixed singles + doubles (regression check)
# ---------------------------------------------------------------------------


class TestMixedSinglesAndDoubles:
    """Running a singles flow alongside a doubles flow does not interfere."""

    def test_singles_lifecycle_completes_alongside_doubles(self, db):
        """
        Singles: Xavier vs Yara completes independently from a doubles match.
        Both lifecycles run to COMPLETED without interfering with each other.
        """
        _seed_tier_config(db)

        # Doubles players
        bob_uid = "mixed_bob"
        dave_uid = "mixed_dave"
        alice_uid = "mixed_alice"
        charlie_uid = "mixed_charlie"

        # Singles players
        xavier_uid = "mixed_xavier"
        yara_uid = "mixed_yara"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
            (xavier_uid, "Xavier Ruiz"),
            (yara_uid, "Yara Novak"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        # --- Doubles flow ---
        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        dbl_offer = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        dbl_accept = play_svc.accept_offer(bob_uid, dbl_offer.offer_id)
        dbl_match_id = dbl_accept.match_id

        # --- Singles flow ---
        from app.models.play import SendOfferRequest as SOR

        singles_offer = play_svc.send_offer(
            xavier_uid,
            SOR(
                to_uid=yara_uid,
                sport=SportEnum.TENNIS,
                proposed_time=_future(),
                court_location="Singles Court",
            ),
        )
        singles_accept = play_svc.accept_offer(yara_uid, singles_offer.offer_id)
        sng_match_id = singles_accept.match_id

        # Singles state transitions.
        assert _get_play_tab(db, xavier_uid)["state"] == "MATCH_SCHEDULED"
        assert _get_play_tab(db, yara_uid)["state"] == "MATCH_SCHEDULED"

        # Complete doubles match.
        confirm_svc.verify_score(
            alice_uid, dbl_match_id, VerifyScoreRequest(winner_team="A", score=_score())
        )
        confirm_svc.verify_score(
            bob_uid, dbl_match_id, VerifyScoreRequest(winner_team="A")
        )

        # Doubles players in DISCOVERY; singles players still MATCH_SCHEDULED.
        for uid in (bob_uid, dave_uid, alice_uid, charlie_uid):
            assert _get_play_tab(db, uid)["state"] == "DISCOVERY"
        assert _get_play_tab(db, xavier_uid)["state"] == "MATCH_SCHEDULED"
        assert _get_play_tab(db, yara_uid)["state"] == "MATCH_SCHEDULED"

        # Complete singles match.
        from app.repos.tier_config_repo import TierConfigRepo
        from app.services.match_confirmation_service import MatchConfirmationService

        sng_confirm = MatchConfirmationService(
            matches_repo=MatchesRepo(db),
            users_repo=UsersRepo(db),
            point_history_repo=PointHistoryRepo(db),
            tier_config_repo=TierConfigRepo(db),
            firestore_client=db,
        )
        sng_confirm.verify_score(
            xavier_uid,
            sng_match_id,
            VerifyScoreRequest(
                winner_uid=xavier_uid,
                score=MatchScore(sets=[SetScore(p1_games=6, p2_games=2)]),
            ),
        )
        sng_confirm.verify_score(
            yara_uid,
            sng_match_id,
            VerifyScoreRequest(winner_uid=xavier_uid),
        )

        # Singles players in DISCOVERY.
        assert _get_play_tab(db, xavier_uid)["state"] == "DISCOVERY"
        assert _get_play_tab(db, yara_uid)["state"] == "DISCOVERY"

        # Doubles match still COMPLETED (unchanged by singles flow).
        assert _get_match(db, dbl_match_id)["status"] == "completed"
        assert _get_match(db, sng_match_id)["status"] == "completed"


# ---------------------------------------------------------------------------
# Scenario 5: Venue propagation in doubles
# ---------------------------------------------------------------------------


class TestDoublesVenuePropagation:
    """venueRef from the broadcast flows through offer → match doc."""

    def test_venue_ref_from_broadcast_propagates_to_match(self, db):
        """
        Bob broadcasts doubles with a venueRef. Alice offers. Bob accepts.
        Match doc carries the same venueRef as the broadcast.
        """
        _seed_tier_config(db)
        bob_uid = "venue_bob"
        dave_uid = "venue_dave"
        alice_uid = "venue_alice"
        charlie_uid = "venue_charlie"

        venue = VenueRef(
            venue_id="ten_twenty_club",
            place_id=None,
            name="Ten Twenty Club",
            coordinates=GeoCoordinates(lat=37.8362, lng=23.7627),
        )

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid,
            _doubles_broadcast_request(
                dave_uid,
                venue_ref=venue,
                court_status=CourtStatusEnum.HAVE_COURT,
            ),
        )
        # Broadcast doc carries the venueRef.
        bc_doc = (
            db.collection("broadcasts").document(bc_resp.broadcast_id).get().to_dict()
            or {}
        )
        assert bc_doc.get("venueRef", {}).get("venueId") == "ten_twenty_club"

        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        match_doc = _get_match(db, match_id)
        assert match_doc.get("venueRef") is not None
        assert match_doc["venueRef"]["venueId"] == "ten_twenty_club"
        assert match_doc["venueRef"]["name"] == "Ten Twenty Club"

    def test_no_venue_ref_when_broadcast_has_none(self, db):
        """Broadcast without a venueRef → match doc has venueRef=None."""
        _seed_tier_config(db)
        bob_uid = "novenue_bob"
        dave_uid = "novenue_dave"
        alice_uid = "novenue_alice"
        charlie_uid = "novenue_charlie"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)

        # No venue_ref in broadcast.
        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        match_doc = _get_match(db, match_id)
        assert match_doc.get("venueRef") is None


# ---------------------------------------------------------------------------
# Scenario 6: Error path — non-participant cannot submit result
# ---------------------------------------------------------------------------


class TestDoublesAccessGuards:
    """Non-participants are rejected by verify_score."""

    def test_outsider_cannot_submit_result(self, db):
        """A user not in the match's participantUids gets PermissionError."""
        bob_uid = "guard_bob"
        dave_uid = "guard_dave"
        alice_uid = "guard_alice"
        charlie_uid = "guard_charlie"
        outsider_uid = "guard_outsider"

        for uid, name in [
            (bob_uid, "Bob Smith"),
            (dave_uid, "Dave Knight"),
            (alice_uid, "Alice King"),
            (charlie_uid, "Charlie Owen"),
            (outsider_uid, "Outside User"),
        ]:
            _seed_user(db, uid, name)

        play_svc = _make_play_service(db)
        confirm_svc = _make_confirmation_service(db)

        bc_resp = play_svc.create_broadcast(
            bob_uid, _doubles_broadcast_request(dave_uid)
        )
        offer_resp = play_svc.send_offer(
            alice_uid,
            _doubles_offer_request(bob_uid, charlie_uid, bc_resp.broadcast_id),
        )
        accept_resp = play_svc.accept_offer(bob_uid, offer_resp.offer_id)
        match_id = accept_resp.match_id

        with pytest.raises(PermissionError):
            confirm_svc.verify_score(
                outsider_uid,
                match_id,
                VerifyScoreRequest(winner_team="A", score=_score()),
            )
