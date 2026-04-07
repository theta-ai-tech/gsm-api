"""
Integration tests for CH-18: feed event types during match confirmation.

Verifies that MatchConfirmationService writes the correct ticker events
to the Firestore ``ticker`` collection when a match is confirmed, covering
personal_best, win_streak, tier_crossed, feedOptOut, and multi-event scenarios.

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via ``make emu-firestore``)

Run:
    make test-int
    # or just this file:
    pytest tests/integration/test_clubhouse_feed_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import app.repos.region_config_repo as region_config_module
import app.repos.tier_config_repo as tier_config_module
from app.models.common import MatchScore, SetScore
from app.models.enums import SportEnum
from app.models.match import VerifyScoreRequest
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.match_confirmation_service import MatchConfirmationService

pytestmark = [pytest.mark.integration]

_SPORT = SportEnum.TENNIS
_SPORT_KEY = "tennis"
_NOW = datetime.now(timezone.utc)

_SCORE_6_3 = MatchScore(
    sets=[SetScore(p1_games=6, p2_games=3)],
    retired=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(db) -> MatchConfirmationService:  # type: ignore[no-untyped-def]
    return MatchConfirmationService(
        matches_repo=MatchesRepo(db),
        users_repo=UsersRepo(db),
        point_history_repo=PointHistoryRepo(db),
        tier_config_repo=TierConfigRepo(db),
        firestore_client=db,
        ticker_repo=TickerRepo(db),
        region_config_repo=RegionConfigRepo(db),
    )


def _seed_tier_config(db) -> None:  # type: ignore[no-untyped-def]
    db.collection("config").document("tiers").set(
        {
            "version": 1,
            "updatedAt": _NOW,
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


def _seed_region_config(db) -> None:  # type: ignore[no-untyped-def]
    db.collection("config").document("regions").set(
        {
            "mapping": {"101": "athens", "202": "thessaloniki"},
            "version": 1,
        }
    )


def _seed_user(  # type: ignore[no-untyped-def]
    db,
    uid: str,
    pts: int = 1500,
    tier: str = "amateur",
    sport: str = "tennis",
    current_streak: int = 0,
    best_streak: int = 0,
    personal_best: int | None = None,
    area: int = 101,
    feed_opt_out: bool = False,
) -> None:
    ranking: dict[str, Any] = {
        "sport": sport,
        "pts": pts,
        "tier": tier,
        "registrationTier": tier,
        "globalRanking": None,
        "lastUpdated": None,
        "currentStreak": current_streak,
        "bestStreak": best_streak,
    }
    if personal_best is not None:
        ranking["personalBest"] = personal_best
    preferences: dict[str, Any] = {
        "area": area,
        "levels": {},
        "sports": [],
    }
    if feed_opt_out:
        preferences["feedOptOut"] = True
    db.collection("users").document(uid).set(
        {
            "name": uid.replace("_", " ").title(),
            "email": f"{uid}@test.com",
            "rankings": {sport: ranking},
            "playTab": {
                "state": "MATCH_SCHEDULED",
                "activeMatchId": None,
                "updatedAt": None,
            },
            "preferences": preferences,
        }
    )


def _seed_match(  # type: ignore[no-untyped-def]
    db,
    match_id: str,
    uid_a: str,
    uid_b: str,
    sport: str = "tennis",
    status: str = "scheduled",
) -> None:
    db.collection("matches").document(match_id).set(
        {
            "sport": sport,
            "status": status,
            "participantUids": [uid_a, uid_b],
            "participants": [
                {"uid": uid_a, "role": "player"},
                {"uid": uid_b, "role": "player"},
            ],
            "scheduledAt": _NOW,
            "score": None,
            "resultByUser": {},
        }
    )


def _confirm_match(  # type: ignore[no-untyped-def]
    db,
    match_id: str,
    winner_uid: str,
    loser_uid: str,
    score: MatchScore = _SCORE_6_3,
    walkover: bool = False,
) -> None:
    """Run the full two-step confirmation flow with ticker + region repos."""
    svc = _make_service(db)
    req = VerifyScoreRequest(winner_uid=winner_uid, score=score, walkover=walkover)
    svc.verify_score(winner_uid, match_id, req)
    svc.verify_score(loser_uid, match_id, req)


def _get_ticker_events(db, event_type: str | None = None) -> list[dict[str, Any]]:
    """Return all ticker docs (optionally filtered by type)."""
    query = db.collection("ticker")
    if event_type:
        query = query.where("type", "==", event_type)
    return [doc.to_dict() for doc in query.stream()]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_caches():
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0
    region_config_module._cache = None
    region_config_module._cache_ts = 0.0
    yield
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0
    region_config_module._cache = None
    region_config_module._cache_ts = 0.0


def _wipe_collections(db) -> None:  # type: ignore[no-untyped-def]
    for doc in db.collection("ticker").stream():
        doc.reference.delete()
    for doc in db.collection("matches").stream():
        doc.reference.delete()
    for doc in db.collection("users").stream():
        for ph in doc.reference.collection("pointHistory").stream():
            ph.reference.delete()
        doc.reference.delete()
    db.collection("config").document("tiers").delete()
    db.collection("config").document("regions").delete()


@pytest.fixture(autouse=True)
def _cleanup_collections(db):
    _wipe_collections(db)
    yield
    _wipe_collections(db)


# ---------------------------------------------------------------------------
# 1. Personal best event
# ---------------------------------------------------------------------------


class TestPersonalBestEvent:
    def test_personal_best_ticker_created_when_winner_exceeds_pb(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner at 1500 with personalBest=1500 — a win gives +100 = 1600 > 1500
        _seed_user(db, "pb_winner", pts=1500, personal_best=1500, area=101)
        _seed_user(db, "pb_loser", pts=1400, area=101)
        _seed_match(db, "pb_match", "pb_winner", "pb_loser")

        _confirm_match(db, "pb_match", "pb_winner", "pb_loser")

        events = _get_ticker_events(db, "personal_best")
        assert len(events) == 1
        evt = events[0]
        assert evt["userUid"] == "pb_winner"
        assert evt["newPts"] == 1600
        assert evt["previousBest"] == 1500
        assert evt["sport"] == "tennis"
        assert evt["region"] == "athens"
        assert "createdAt" in evt
        assert "expiresAt" in evt

    def test_no_personal_best_ticker_when_pts_below_pb(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner at 1500 with personalBest=1800 — a win gives 1600 < 1800
        _seed_user(db, "pb2_winner", pts=1500, personal_best=1800, area=101)
        _seed_user(db, "pb2_loser", pts=1400, area=101)
        _seed_match(db, "pb2_match", "pb2_winner", "pb2_loser")

        _confirm_match(db, "pb2_match", "pb2_winner", "pb2_loser")

        events = _get_ticker_events(db, "personal_best")
        assert len(events) == 0


# ---------------------------------------------------------------------------
# 2. Win streak milestone (streak reaches 3)
# ---------------------------------------------------------------------------


class TestWinStreakMilestone:
    def test_win_streak_ticker_created_at_streak_3(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner has currentStreak=2, next win brings it to 3 (a milestone)
        _seed_user(
            db,
            "ws_winner",
            pts=1500,
            current_streak=2,
            best_streak=2,
            personal_best=1800,
            area=101,
        )
        _seed_user(db, "ws_loser", pts=1400, area=101)
        _seed_match(db, "ws_match", "ws_winner", "ws_loser")

        _confirm_match(db, "ws_match", "ws_winner", "ws_loser")

        events = _get_ticker_events(db, "win_streak")
        assert len(events) == 1
        evt = events[0]
        assert evt["userUid"] == "ws_winner"
        assert evt["streak"] == 3
        assert evt["sport"] == "tennis"
        assert evt["region"] == "athens"


# ---------------------------------------------------------------------------
# 3. Tier crossed event
# ---------------------------------------------------------------------------


class TestTierCrossedEvent:
    def test_tier_crossed_ticker_on_promotion(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner at 1950 (amateur, max 1999) — a win gives +100 = 2050 → intermediate
        _seed_user(
            db,
            "tc_winner",
            pts=1950,
            tier="amateur",
            personal_best=1950,
            area=101,
        )
        _seed_user(db, "tc_loser", pts=1900, tier="amateur", area=101)
        _seed_match(db, "tc_match", "tc_winner", "tc_loser")

        _confirm_match(db, "tc_match", "tc_winner", "tc_loser")

        events = _get_ticker_events(db, "tier_crossed")
        # Only the winner crosses a tier in this scenario
        winner_events = [e for e in events if e.get("userUid") == "tc_winner"]
        assert len(winner_events) == 1
        evt = winner_events[0]
        assert evt["userUid"] == "tc_winner"
        assert evt["tierBefore"] == "amateur"
        assert evt["tierAfter"] == "intermediate"
        assert evt["direction"] == "up"
        assert evt["sport"] == "tennis"
        assert evt["region"] == "athens"
        assert "createdAt" in evt
        assert "expiresAt" in evt

    def test_tier_crossed_ticker_on_demotion(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Loser at 2050 (intermediate, min 2000) — a loss gives -100 = 1950 → amateur
        _seed_user(
            db,
            "dem_winner",
            pts=1950,
            tier="amateur",
            personal_best=1950,
            area=101,
        )
        _seed_user(
            db,
            "dem_loser",
            pts=2050,
            tier="intermediate",
            area=101,
        )
        _seed_match(db, "dem_match", "dem_winner", "dem_loser")

        _confirm_match(db, "dem_match", "dem_winner", "dem_loser")

        events = _get_ticker_events(db, "tier_crossed")
        loser_events = [e for e in events if e.get("userUid") == "dem_loser"]
        assert len(loser_events) == 1
        evt = loser_events[0]
        assert evt["userUid"] == "dem_loser"
        assert evt["tierBefore"] == "intermediate"
        assert evt["tierAfter"] == "amateur"
        assert evt["direction"] == "down"
        assert evt["sport"] == "tennis"
        assert evt["region"] == "athens"
        assert "createdAt" in evt
        assert "expiresAt" in evt


# ---------------------------------------------------------------------------
# 4. No event on non-milestone streak (1 → 2)
# ---------------------------------------------------------------------------


class TestNoEventNonMilestoneStreak:
    def test_no_win_streak_ticker_when_streak_goes_1_to_2(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner has currentStreak=1, next win brings it to 2 (not a milestone)
        _seed_user(
            db,
            "nms_winner",
            pts=1500,
            current_streak=1,
            best_streak=1,
            personal_best=1800,
            area=101,
        )
        _seed_user(db, "nms_loser", pts=1400, area=101)
        _seed_match(db, "nms_match", "nms_winner", "nms_loser")

        _confirm_match(db, "nms_match", "nms_winner", "nms_loser")

        events = _get_ticker_events(db, "win_streak")
        assert len(events) == 0


# ---------------------------------------------------------------------------
# 5. No event for loss
# ---------------------------------------------------------------------------


class TestNoEventForLoss:
    def test_loser_streak_resets_but_no_ticker_event(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Loser had a streak of 3 — it resets to 0 but no ticker event written
        _seed_user(db, "nel_winner", pts=1500, personal_best=1800, area=101)
        _seed_user(
            db,
            "nel_loser",
            pts=1400,
            current_streak=3,
            best_streak=3,
            area=101,
        )
        _seed_match(db, "nel_match", "nel_winner", "nel_loser")

        _confirm_match(db, "nel_match", "nel_winner", "nel_loser")

        # Filter out winner's events — check no event references the loser's UID
        all_events = _get_ticker_events(db)
        loser_events = [
            e
            for e in all_events
            if e.get("userUid") == "nel_loser" or e.get("winnerUid") == "nel_loser"
        ]
        assert len(loser_events) == 0


# ---------------------------------------------------------------------------
# 6. feedOptOut respected
# ---------------------------------------------------------------------------


class TestFeedOptOutRespected:
    def test_no_ticker_events_when_winner_has_feed_opt_out(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner opts out of feed — even though they get a personal best + streak milestone,
        # no ticker events should be written for the winner
        _seed_user(
            db,
            "opt_winner",
            pts=1500,
            current_streak=2,
            best_streak=2,
            personal_best=1500,
            area=101,
            feed_opt_out=True,
        )
        _seed_user(db, "opt_loser", pts=1400, area=101)
        _seed_match(db, "opt_match", "opt_winner", "opt_loser")

        _confirm_match(db, "opt_match", "opt_winner", "opt_loser")

        all_events = _get_ticker_events(db)
        # No events referencing winner
        winner_events = [
            e
            for e in all_events
            if e.get("userUid") == "opt_winner" or e.get("winnerUid") == "opt_winner"
        ]
        assert len(winner_events) == 0


# ---------------------------------------------------------------------------
# 7. Multiple events in single match
# ---------------------------------------------------------------------------


class TestMultipleEventsInSingleMatch:
    def test_upset_personal_best_and_streak_all_created(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Amateur (1800) beats intermediate (2200):
        #   upset ticker (winner_tier < loser_tier)
        #   personal_best ticker (1800 + 170 = 1970 > 1800)
        #   win_streak ticker (streak goes from 2 → 3, a milestone)
        _seed_user(
            db,
            "multi_winner",
            pts=1800,
            tier="amateur",
            current_streak=2,
            best_streak=2,
            personal_best=1800,
            area=101,
        )
        _seed_user(
            db,
            "multi_loser",
            pts=2200,
            tier="intermediate",
            area=101,
        )
        _seed_match(db, "multi_match", "multi_winner", "multi_loser")

        _confirm_match(db, "multi_match", "multi_winner", "multi_loser")

        # Assert each expected event type separately with scoped field checks
        upset_events = _get_ticker_events(db, "upset")
        assert len(upset_events) == 1
        assert upset_events[0]["winnerUid"] == "multi_winner"

        pb_events = _get_ticker_events(db, "personal_best")
        assert len(pb_events) == 1
        assert pb_events[0]["userUid"] == "multi_winner"

        streak_events = _get_ticker_events(db, "win_streak")
        assert len(streak_events) == 1
        assert streak_events[0]["userUid"] == "multi_winner"
        assert streak_events[0]["streak"] == 3

    def test_upset_event_has_correct_fields(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        _seed_user(
            db,
            "multi2_winner",
            pts=1800,
            tier="amateur",
            current_streak=2,
            best_streak=2,
            personal_best=1800,
            area=101,
        )
        _seed_user(
            db,
            "multi2_loser",
            pts=2200,
            tier="intermediate",
            area=101,
        )
        _seed_match(db, "multi2_match", "multi2_winner", "multi2_loser")

        _confirm_match(db, "multi2_match", "multi2_winner", "multi2_loser")

        upset_events = _get_ticker_events(db, "upset")
        assert len(upset_events) == 1
        evt = upset_events[0]
        assert evt["winnerUid"] == "multi2_winner"
        assert evt["loserTier"] == "intermediate"
        # base(100) + upset(50) + elo(floor(400*0.05)=20) = 170
        assert evt["delta"] == 170


# ---------------------------------------------------------------------------
# 8. Region derivation
# ---------------------------------------------------------------------------


class TestRegionDerivation:
    def test_ticker_event_region_matches_user_area(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner with area=202 → should map to "thessaloniki"
        _seed_user(db, "reg_winner", pts=1500, personal_best=1500, area=202)
        _seed_user(db, "reg_loser", pts=1400, area=101)
        _seed_match(db, "reg_match", "reg_winner", "reg_loser")

        _confirm_match(db, "reg_match", "reg_winner", "reg_loser")

        pb_events = _get_ticker_events(db, "personal_best")
        assert len(pb_events) == 1
        assert pb_events[0]["region"] == "thessaloniki"

    def test_no_ticker_when_area_has_no_region_mapping(self, db) -> None:
        _seed_tier_config(db)
        _seed_region_config(db)
        # Winner with area=999 → no mapping → no ticker events for winner
        _seed_user(db, "noreg_winner", pts=1500, personal_best=1500, area=999)
        _seed_user(db, "noreg_loser", pts=1400, area=101)
        _seed_match(db, "noreg_match", "noreg_winner", "noreg_loser")

        _confirm_match(db, "noreg_match", "noreg_winner", "noreg_loser")

        all_events = _get_ticker_events(db)
        winner_events = [
            e
            for e in all_events
            if e.get("userUid") == "noreg_winner"
            or e.get("winnerUid") == "noreg_winner"
        ]
        assert len(winner_events) == 0
