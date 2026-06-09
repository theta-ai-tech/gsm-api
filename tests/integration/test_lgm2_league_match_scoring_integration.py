"""
Integration tests for LGM-2: leagueId reaches scoring + standings.

Proves end-to-end that:
1. A completed league doubles match updates member stats (wins/losses) via
   the ``handle_match_write_update_league_stats`` trigger.
2. ``GET /leagues/{leagueId}/standings`` reflects the updated 1-0 / 0-1 standings.
3. Re-firing the trigger with the same before/after docs does NOT double-count
   (idempotency via ``processedMatchIds``).

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. ``make emu-all``).
"""

from __future__ import annotations

import app.repos.tier_config_repo as tier_config_module
import pytest

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient

from app.dependencies.repos import get_league_service, get_leagues_repo
from app.deps import get_current_user, get_role_service
from app.main import app
from app.models.common import MatchScore, SetScore
from app.models.enums import (
    AvailabilityEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    MatchTypeEnum,
    SportEnum,
)
from app.models.match import VerifyScoreRequest
from app.models.play import BroadcastLocation, CreateBroadcastRequest, SendOfferRequest
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService
from app.services.match_confirmation_service import MatchConfirmationService
from app.services.play_service import PlayService
from app.services.role_service import RoleService
from functions.scoring_triggers.main import handle_match_write_update_league_stats

pytestmark = [pytest.mark.integration]

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_LEAGUE_ID = "int-test-lgm2-league"
_SPORT = SportEnum.PADEL
_SPORT_VALUE = "padel"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future(hours: float = 2.0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _score() -> MatchScore:
    return MatchScore(
        sets=[SetScore(p1_games=6, p2_games=3), SetScore(p1_games=6, p2_games=4)]
    )


def _seed_user(
    db: Any, uid: str, name: str, pts: int = 1000, tier: str = "amateur"
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


def _seed_tier_config(db: Any) -> None:
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


def _seed_league_with_members(db: Any, member_uids: list[str]) -> None:
    now = datetime.now(timezone.utc)
    db.collection("leagues").document(_LEAGUE_ID).set(
        {
            "name": "LGM-2 Test League",
            "sport": "padel",
            "status": "active",
            "ownerUid": member_uids[0],
            "region": "athens",
            "maxPlayers": 10,
            "currentPlayers": len(member_uids),
            "startDate": now,
            "endDate": datetime(2027, 1, 1, tzinfo=timezone.utc),
            "tier": "amateur",
        }
    )
    for uid in member_uids:
        db.collection("leagues").document(_LEAGUE_ID).collection("members").document(
            uid
        ).set(
            {
                "role": "player",
                "status": "active",
                "joinedAt": now,
                "stats": None,
            }
        )


def _make_play_service(db: Any) -> PlayService:
    return PlayService(
        UsersRepo(db),
        BroadcastsRepo(db),
        MatchesRepo(db),
        OffersRepo(db),
        db,
        leagues_repo=LeaguesRepo(db),
    )


def _make_confirmation_service(db: Any) -> MatchConfirmationService:
    return MatchConfirmationService(
        matches_repo=MatchesRepo(db),
        users_repo=UsersRepo(db),
        point_history_repo=PointHistoryRepo(db),
        tier_config_repo=TierConfigRepo(db),
        firestore_client=db,
    )


def _get_member_doc(db: Any, uid: str) -> dict[str, Any]:
    doc = (
        db.collection("leagues")
        .document(_LEAGUE_ID)
        .collection("members")
        .document(uid)
        .get()
    )
    return doc.to_dict() or {}


def _wipe_league_and_matches(db: Any, member_uids: list[str]) -> None:
    """Delete all collections that LGM-2 tests write to."""
    for coll in ("broadcasts", "offers", "matches"):
        for doc in db.collection(coll).stream():
            doc.reference.delete()
    for doc in db.collection("config").stream():
        doc.reference.delete()
    # Wipe league members subcollection before league doc (order matters for consistency)
    for uid in member_uids:
        (
            db.collection("leagues")
            .document(_LEAGUE_ID)
            .collection("members")
            .document(uid)
            .delete()
        )
    db.collection("leagues").document(_LEAGUE_ID).delete()
    # Wipe user pointHistory subcollections
    for user_doc in db.collection("users").stream():
        for ph in (
            db.collection("users")
            .document(user_doc.id)
            .collection("pointHistory")
            .stream()
        ):
            ph.reference.delete()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MEMBER_UIDS = [
    "lgm2_bob",
    "lgm2_dave",
    "lgm2_alice",
    "lgm2_charlie",
]


@pytest.fixture(autouse=True)
def _cleanup_league_and_matches(db: Any):
    """Wipe touched collections before and after each test for isolation."""
    _wipe_league_and_matches(db, _MEMBER_UIDS)
    yield
    _wipe_league_and_matches(db, _MEMBER_UIDS)


@pytest.fixture(autouse=True)
def _reset_tier_cache():
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0
    yield
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0


# ---------------------------------------------------------------------------
# Helper: full league doubles flow up to (and including) trigger call
# ---------------------------------------------------------------------------


def _run_full_league_doubles_flow(
    db: Any,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """
    Run the full doubles league flow:
      1. Seed tier config + 4 users + league with members
      2. broadcast → offer (with league_id) → accept
      3. First verify_score (Alice, Team B, winner_team=A, with score)
      4. Read before_doc (status=pending_confirmation)
      5. Second verify_score (Bob, Team A, winner_team=A, confirms)
      6. Read after_doc (status=completed)

    Returns (match_id, before_doc, after_doc).
    """
    bob_uid, dave_uid, alice_uid, charlie_uid = _MEMBER_UIDS

    _seed_tier_config(db)
    for uid, name in [
        (bob_uid, "Bob Smith"),
        (dave_uid, "Dave Knight"),
        (alice_uid, "Alice King"),
        (charlie_uid, "Charlie Owen"),
    ]:
        _seed_user(db, uid, name)

    _seed_league_with_members(db, [bob_uid, dave_uid, alice_uid, charlie_uid])

    play_svc = _make_play_service(db)
    confirm_svc = _make_confirmation_service(db)

    # Bob (Team A) broadcasts doubles + find_opponent with Dave as partner.
    bc_resp = play_svc.create_broadcast(
        bob_uid,
        CreateBroadcastRequest(
            sport=_SPORT,
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
            partner_uid=dave_uid,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location="Test Court",
            expires_at=_future(),
            location=BroadcastLocation(area=10001),
        ),
    )
    broadcast_id = bc_resp.broadcast_id

    # Alice (Team B) sends offer with Charlie as partner and league_id attached.
    offer_resp = play_svc.send_offer(
        alice_uid,
        SendOfferRequest(
            to_uid=bob_uid,
            sport=_SPORT,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid=charlie_uid,
            proposed_time=_future(),
            source_broadcast_id=broadcast_id,
            court_location="Test Court",
            message="League match!",
            league_id=_LEAGUE_ID,
        ),
    )
    offer_id = offer_resp.offer_id

    # Bob accepts → match created.
    accept_resp = play_svc.accept_offer(bob_uid, offer_id)
    match_id = accept_resp.match_id
    assert match_id

    # Alice (Team B) submits result: winner_team=A (score required on first submission).
    confirm_svc.verify_score(
        alice_uid, match_id, VerifyScoreRequest(winner_team="A", score=_score())
    )

    # Read before_doc now (status=pending_confirmation).
    before_doc = db.collection("matches").document(match_id).get().to_dict()
    assert before_doc is not None
    assert before_doc["status"] == "pending_confirmation"

    # Bob (Team A) confirms: winner_team=A → match COMPLETED.
    confirm_svc.verify_score(bob_uid, match_id, VerifyScoreRequest(winner_team="A"))

    # Read after_doc (status=completed).
    after_doc = db.collection("matches").document(match_id).get().to_dict()
    assert after_doc is not None
    assert after_doc["status"] == "completed"

    # Inject matchId: Cloud Functions receive it from the event resource path, not the
    # doc body. Direct trigger invocation in tests requires explicit injection so that
    # increment_member_stats stores the real match_id in processedMatchIds.
    before_doc["matchId"] = match_id
    after_doc["matchId"] = match_id

    return match_id, before_doc, after_doc


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestLeagueMatchScoringAndStandings:
    """Proves leagueId flows from offer → match → trigger → member stats → standings."""

    def test_doubles_league_match_updates_member_stats_and_standings(
        self, db: Any
    ) -> None:
        """
        Full end-to-end: league doubles match completion updates member stats and
        GET /leagues/{leagueId}/standings reflects 1-0 / 0-1.
        """
        bob_uid, dave_uid, alice_uid, charlie_uid = _MEMBER_UIDS

        match_id, before_doc, after_doc = _run_full_league_doubles_flow(db)

        # Verify leagueId and resultByUser are present in the completed match doc.
        assert after_doc.get("leagueId") == _LEAGUE_ID, (
            f"Expected leagueId={_LEAGUE_ID!r}, got {after_doc.get('leagueId')!r}"
        )
        result_by_user = after_doc.get("resultByUser") or {}
        assert result_by_user, "resultByUser should be non-empty after completion"

        # Call the trigger directly (Cloud Function triggers don't auto-fire in emulator tests).
        handle_match_write_update_league_stats(db, before_doc, after_doc)

        # Assert winner member stats.
        bob_member = _get_member_doc(db, bob_uid)
        dave_member = _get_member_doc(db, dave_uid)
        assert (bob_member.get("stats") or {}).get("wins") == 1, (
            f"bob_uid: expected stats.wins==1, got {bob_member.get('stats')}"
        )
        assert (dave_member.get("stats") or {}).get("wins") == 1, (
            f"dave_uid: expected stats.wins==1, got {dave_member.get('stats')}"
        )

        # Assert loser member stats.
        alice_member = _get_member_doc(db, alice_uid)
        charlie_member = _get_member_doc(db, charlie_uid)
        assert (alice_member.get("stats") or {}).get("losses") == 1, (
            f"alice_uid: expected stats.losses==1, got {alice_member.get('stats')}"
        )
        assert (charlie_member.get("stats") or {}).get("losses") == 1, (
            f"charlie_uid: expected stats.losses==1, got {charlie_member.get('stats')}"
        )

        # Assert processedMatchIds for all 4 members.
        for uid in (bob_uid, dave_uid, alice_uid, charlie_uid):
            member = _get_member_doc(db, uid)
            processed = member.get("processedMatchIds") or []
            assert match_id in processed, (
                f"{uid}: expected {match_id!r} in processedMatchIds, got {processed}"
            )

        # Assert standings via FastAPI TestClient.
        prev = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=bob_uid, email="lgm2_bob@test.com"
        )
        app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
        app.dependency_overrides[get_league_service] = lambda: LeagueService(
            LeaguesRepo(db), db
        )
        app.dependency_overrides[get_role_service] = lambda: RoleService(db=db)

        client = TestClient(app)
        resp = client.get(f"/leagues/{_LEAGUE_ID}/standings")
        assert resp.status_code == 200, (
            f"standings returned {resp.status_code}: {resp.text}"
        )

        standings = resp.json().get("standings") or []
        assert standings, "standings should be non-empty"

        winner_entries = [e for e in standings if e["uid"] in (bob_uid, dave_uid)]
        loser_entries = [e for e in standings if e["uid"] in (alice_uid, charlie_uid)]

        assert len(winner_entries) == 2, (
            f"Expected 2 winner entries, got {winner_entries}"
        )
        assert len(loser_entries) == 2, f"Expected 2 loser entries, got {loser_entries}"

        for entry in winner_entries:
            assert entry["rank"] == 1, (
                f"Winner {entry['uid']} should be rank 1, got {entry}"
            )
            assert entry["wins"] == 1, (
                f"Winner {entry['uid']} should have wins=1, got {entry}"
            )
            assert entry["losses"] == 0, (
                f"Winner {entry['uid']} should have losses=0, got {entry}"
            )

        for entry in loser_entries:
            assert entry["rank"] == 2, (
                f"Loser {entry['uid']} should be rank 2, got {entry}"
            )
            assert entry["wins"] == 0, (
                f"Loser {entry['uid']} should have wins=0, got {entry}"
            )
            assert entry["losses"] == 1, (
                f"Loser {entry['uid']} should have losses=1, got {entry}"
            )

        app.dependency_overrides = prev

    def test_trigger_refire_does_not_double_count(self, db: Any) -> None:
        """
        Re-firing the trigger with the same before/after docs does not double-count
        wins/losses — the ``processedMatchIds`` guard in ``increment_member_stats``
        prevents double writes.
        """
        bob_uid, dave_uid, alice_uid, charlie_uid = _MEMBER_UIDS

        match_id, before_doc, after_doc = _run_full_league_doubles_flow(db)

        # First trigger call — should apply stats.
        handle_match_write_update_league_stats(db, before_doc, after_doc)

        # Verify first call applied correctly.
        bob_member = _get_member_doc(db, bob_uid)
        assert (bob_member.get("stats") or {}).get("wins") == 1, (
            f"After 1st trigger: bob_uid expected wins==1, got {bob_member.get('stats')}"
        )

        # Second trigger call with identical before/after docs — must be a no-op.
        handle_match_write_update_league_stats(db, before_doc, after_doc)

        # Stats must still be 1, not 2.
        bob_member_after = _get_member_doc(db, bob_uid)
        dave_member_after = _get_member_doc(db, dave_uid)
        alice_member_after = _get_member_doc(db, alice_uid)
        charlie_member_after = _get_member_doc(db, charlie_uid)

        assert (bob_member_after.get("stats") or {}).get("wins") == 1, (
            f"After 2nd trigger: bob_uid expected wins==1 (no double-count), "
            f"got {bob_member_after.get('stats')}"
        )
        assert (dave_member_after.get("stats") or {}).get("wins") == 1, (
            f"After 2nd trigger: dave_uid expected wins==1, got {dave_member_after.get('stats')}"
        )
        assert (alice_member_after.get("stats") or {}).get("losses") == 1, (
            f"After 2nd trigger: alice_uid expected losses==1, got {alice_member_after.get('stats')}"
        )
        assert (charlie_member_after.get("stats") or {}).get("losses") == 1, (
            f"After 2nd trigger: charlie_uid expected losses==1, got {charlie_member_after.get('stats')}"
        )

        # processedMatchIds should contain match_id exactly once (lists may have duplicates
        # if idempotency failed — we only check the stats here; the guard prevents double-write).
        for uid in (bob_uid, dave_uid, alice_uid, charlie_uid):
            member = _get_member_doc(db, uid)
            processed = member.get("processedMatchIds") or []
            count = processed.count(match_id)
            assert count == 1, (
                f"{uid}: match_id should appear exactly once in processedMatchIds, "
                f"found {count} times"
            )
