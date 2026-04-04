"""
Integration tests for match confirmation + scoring transaction (SE-14).

Verifies the full two-step verify-score flow against the real Firestore
emulator: seeded users and matches, real MatchConfirmationService, then
assertions against the resulting Firestore state.

Requires: FIRESTORE_EMULATOR_HOST env var set (e.g. via `make emu-all`)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

import app.repos.region_config_repo as region_config_module
import app.repos.tier_config_repo as tier_config_module
from app.models.common import MatchScore, SetScore
from app.models.enums import (
    MatchResultEnum,
    MatchStatusEnum,
    PointHistoryReasonEnum,
    SportEnum,
    TierEnum,
)
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
_NOW = datetime.now(timezone.utc)

_SCORE = MatchScore(
    sets=[SetScore(p1_games=6, p2_games=3)],
    retired=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(db) -> MatchConfirmationService:
    return MatchConfirmationService(
        matches_repo=MatchesRepo(db),
        users_repo=UsersRepo(db),
        point_history_repo=PointHistoryRepo(db),
        tier_config_repo=TierConfigRepo(db),
        firestore_client=db,
    )


def seed_tier_config(db) -> None:
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


def seed_user(
    db,
    uid: str,
    pts: int = 1500,
    tier: str = "amateur",
    sport: str = "tennis",
) -> None:
    db.collection("users").document(uid).set(
        {
            "name": uid,
            "email": f"{uid}@test.com",
            "rankings": {
                sport: {
                    "sport": sport,
                    "pts": pts,
                    "tier": tier,
                    "registrationTier": tier,
                    "globalRanking": None,
                    "lastUpdated": None,
                }
            },
            "playTab": {
                "state": "MATCH_SCHEDULED",
                "activeMatchId": None,
                "updatedAt": None,
            },
        }
    )


def seed_match(
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


def get_user_pts(db, uid: str, sport: str = "tennis") -> int:
    doc = db.collection("users").document(uid).get().to_dict() or {}
    return (doc.get("rankings") or {}).get(sport, {}).get("pts", 0)


def get_user_tier(db, uid: str, sport: str = "tennis") -> str:
    doc = db.collection("users").document(uid).get().to_dict() or {}
    return (doc.get("rankings") or {}).get(sport, {}).get("tier", "")


def get_match_status(db, match_id: str) -> str:
    doc = db.collection("matches").document(match_id).get().to_dict() or {}
    return doc.get("status", "")


def get_point_history(db, uid: str, sport: str = "tennis") -> list[dict]:
    entries = (
        db.collection("users")
        .document(uid)
        .collection("pointHistory")
        .where("sport", "==", sport)
        .stream()
    )
    return [e.to_dict() for e in entries]


def confirm_match(db, match_id: str, winner_uid: str, loser_uid: str) -> None:
    """Run the full two-step confirmation flow."""
    svc = make_service(db)
    req = VerifyScoreRequest(winner_uid=winner_uid, score=_SCORE)
    svc.verify_score(winner_uid, match_id, req)
    svc.verify_score(loser_uid, match_id, req)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tier_cache():
    """Invalidate the module-level TierConfigRepo cache before each test."""
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0
    yield
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0


@pytest.fixture(autouse=True)
def _cleanup_matches(db):
    yield
    for doc in db.collection("matches").stream():
        doc.reference.delete()
    for doc in db.collection("users").stream():
        for ph in doc.reference.collection("pointHistory").stream():
            ph.reference.delete()
    db.collection("config").document("tiers").delete()


# ---------------------------------------------------------------------------
# SC-01: Happy path — same-tier match
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_match_status_becomes_completed(self, db):
        seed_tier_config(db)
        seed_user(db, "sc01_winner", pts=1500, tier="amateur")
        seed_user(db, "sc01_loser", pts=1400, tier="amateur")
        seed_match(db, "sc01_match", "sc01_winner", "sc01_loser")

        confirm_match(db, "sc01_match", "sc01_winner", "sc01_loser")

        assert get_match_status(db, "sc01_match") == MatchStatusEnum.COMPLETED

    def test_winner_points_increase_by_base(self, db):
        seed_tier_config(db)
        seed_user(db, "sc01b_winner", pts=1500, tier="amateur")
        seed_user(db, "sc01b_loser", pts=1400, tier="amateur")
        seed_match(db, "sc01b_match", "sc01b_winner", "sc01b_loser")

        confirm_match(db, "sc01b_match", "sc01b_winner", "sc01b_loser")

        assert get_user_pts(db, "sc01b_winner") == 1600  # +100 base

    def test_loser_points_unchanged_same_tier(self, db):
        seed_tier_config(db)
        seed_user(db, "sc01c_winner", pts=1500, tier="amateur")
        seed_user(db, "sc01c_loser", pts=1400, tier="amateur")
        seed_match(db, "sc01c_match", "sc01c_winner", "sc01c_loser")

        confirm_match(db, "sc01c_match", "sc01c_winner", "sc01c_loser")

        assert get_user_pts(db, "sc01c_loser") == 1400  # no penalty same tier

    def test_point_history_entries_created_for_both_players(self, db):
        seed_tier_config(db)
        seed_user(db, "sc01d_winner", pts=1500, tier="amateur")
        seed_user(db, "sc01d_loser", pts=1400, tier="amateur")
        seed_match(db, "sc01d_match", "sc01d_winner", "sc01d_loser")

        confirm_match(db, "sc01d_match", "sc01d_winner", "sc01d_loser")

        winner_history = get_point_history(db, "sc01d_winner")
        loser_history = get_point_history(db, "sc01d_loser")
        assert len(winner_history) == 1
        assert len(loser_history) == 1

    def test_winner_history_entry_has_correct_fields(self, db):
        seed_tier_config(db)
        seed_user(db, "sc01e_winner", pts=1500, tier="amateur")
        seed_user(db, "sc01e_loser", pts=1400, tier="amateur")
        seed_match(db, "sc01e_match", "sc01e_winner", "sc01e_loser")

        confirm_match(db, "sc01e_match", "sc01e_winner", "sc01e_loser")

        entry = get_point_history(db, "sc01e_winner")[0]
        assert entry["pts"] == 1600
        assert entry["delta"] == 100
        assert entry["reason"] == PointHistoryReasonEnum.MATCH_WIN
        assert entry["matchId"] == "sc01e_match"

    def test_result_by_user_set_on_match(self, db):
        seed_tier_config(db)
        seed_user(db, "sc01f_winner", pts=1500, tier="amateur")
        seed_user(db, "sc01f_loser", pts=1400, tier="amateur")
        seed_match(db, "sc01f_match", "sc01f_winner", "sc01f_loser")

        confirm_match(db, "sc01f_match", "sc01f_winner", "sc01f_loser")

        doc = db.collection("matches").document("sc01f_match").get().to_dict() or {}
        result_by_user = doc.get("resultByUser", {})
        assert result_by_user.get("sc01f_winner") == MatchResultEnum.WIN
        assert result_by_user.get("sc01f_loser") == MatchResultEnum.LOSS

    def test_play_tab_reset_to_discovery(self, db):
        seed_tier_config(db)
        seed_user(db, "sc01g_winner", pts=1500, tier="amateur")
        seed_user(db, "sc01g_loser", pts=1400, tier="amateur")
        seed_match(db, "sc01g_match", "sc01g_winner", "sc01g_loser")

        confirm_match(db, "sc01g_match", "sc01g_winner", "sc01g_loser")

        for uid in ("sc01g_winner", "sc01g_loser"):
            doc = db.collection("users").document(uid).get().to_dict() or {}
            assert doc.get("playTab", {}).get("state") == "DISCOVERY"


# ---------------------------------------------------------------------------
# SC-02: Upset scenario — lower-tier beats higher-tier
# ---------------------------------------------------------------------------


class TestUpsetScenario:
    def test_upset_winner_gets_base_plus_bonus(self, db):
        # amateur (1800) beats intermediate (2200): upset_bonus=50, elo_bonus=floor(400*0.05)=20
        seed_tier_config(db)
        seed_user(db, "sc02_winner", pts=1800, tier="amateur")
        seed_user(db, "sc02_loser", pts=2200, tier="intermediate")
        seed_match(db, "sc02_match", "sc02_winner", "sc02_loser")

        confirm_match(db, "sc02_match", "sc02_winner", "sc02_loser")

        assert get_user_pts(db, "sc02_winner") == 1800 + 100 + 50 + 20  # 1970

    def test_upset_loser_takes_penalty(self, db):
        seed_tier_config(db)
        seed_user(db, "sc02b_winner", pts=1800, tier="amateur")
        seed_user(db, "sc02b_loser", pts=2200, tier="intermediate")
        seed_match(db, "sc02b_match", "sc02b_winner", "sc02b_loser")

        confirm_match(db, "sc02b_match", "sc02b_winner", "sc02b_loser")

        assert get_user_pts(db, "sc02b_loser") == 2200 - 50  # 2150

    def test_upset_winner_crosses_tier(self, db):
        # amateur at 1950 + 170 = 2120 → crosses into intermediate
        seed_tier_config(db)
        seed_user(db, "sc02c_winner", pts=1950, tier="amateur")
        seed_user(db, "sc02c_loser", pts=2950, tier="intermediate")
        seed_match(db, "sc02c_match", "sc02c_winner", "sc02c_loser")

        confirm_match(db, "sc02c_match", "sc02c_winner", "sc02c_loser")

        assert get_user_tier(db, "sc02c_winner") == TierEnum.INTERMEDIATE

    def test_upset_loser_history_entry_reason_is_match_loss(self, db):
        seed_tier_config(db)
        seed_user(db, "sc02d_winner", pts=1800, tier="amateur")
        seed_user(db, "sc02d_loser", pts=2200, tier="intermediate")
        seed_match(db, "sc02d_match", "sc02d_winner", "sc02d_loser")

        confirm_match(db, "sc02d_match", "sc02d_winner", "sc02d_loser")

        entry = get_point_history(db, "sc02d_loser")[0]
        assert entry["reason"] == PointHistoryReasonEnum.MATCH_LOSS
        assert entry["delta"] == -50


# ---------------------------------------------------------------------------
# SC-03: Floor enforcement
# ---------------------------------------------------------------------------


class TestFloorEnforcement:
    def test_loser_at_floor_pts_stay_at_floor(self, db):
        # intermediate at floor (2000) loses to amateur → penalty would go below floor → clamped
        seed_tier_config(db)
        seed_user(db, "sc03_winner", pts=1800, tier="amateur")
        seed_user(db, "sc03_loser", pts=2000, tier="intermediate")
        seed_match(db, "sc03_match", "sc03_winner", "sc03_loser")

        confirm_match(db, "sc03_match", "sc03_winner", "sc03_loser")

        assert get_user_pts(db, "sc03_loser") == 2000  # clamped at floor

    def test_loser_just_above_floor_loses_exactly_to_floor(self, db):
        # intermediate at 2050 loses to amateur → 2050 - 50 = 2000 (no clamping needed)
        seed_tier_config(db)
        seed_user(db, "sc03b_winner", pts=1800, tier="amateur")
        seed_user(db, "sc03b_loser", pts=2050, tier="intermediate")
        seed_match(db, "sc03b_match", "sc03b_winner", "sc03b_loser")

        confirm_match(db, "sc03b_match", "sc03b_winner", "sc03b_loser")

        assert get_user_pts(db, "sc03b_loser") == 2000

    def test_floor_effective_delta_reflects_actual_change(self, db):
        # 2010 - 50 raw = 1960 < floor 2000 → clamped to 2000 → effective delta = -10
        seed_tier_config(db)
        seed_user(db, "sc03c_winner", pts=1800, tier="amateur")
        seed_user(db, "sc03c_loser", pts=2010, tier="intermediate")
        seed_match(db, "sc03c_match", "sc03c_winner", "sc03c_loser")

        confirm_match(db, "sc03c_match", "sc03c_winner", "sc03c_loser")

        entry = get_point_history(db, "sc03c_loser")[0]
        assert entry["delta"] == -10  # effective, not raw penalty
        assert entry["pts"] == 2000


# ---------------------------------------------------------------------------
# SC-04: Transaction atomicity (first-submission state check)
# ---------------------------------------------------------------------------


class TestTransactionAtomicity:
    def test_first_submission_sets_pending_confirmation_only(self, db):
        """After the first verify-score call, match is pending_confirmation and
        user rankings are not yet updated — scoring only happens on the second call."""
        seed_tier_config(db)
        seed_user(db, "sc04_winner", pts=1500, tier="amateur")
        seed_user(db, "sc04_loser", pts=1400, tier="amateur")
        seed_match(db, "sc04_match", "sc04_winner", "sc04_loser")

        svc = make_service(db)
        req = VerifyScoreRequest(winner_uid="sc04_winner", score=_SCORE)
        svc.verify_score("sc04_winner", "sc04_match", req)

        assert (
            get_match_status(db, "sc04_match") == MatchStatusEnum.PENDING_CONFIRMATION
        )
        assert (
            get_user_pts(db, "sc04_winner") == 1500
        )  # unchanged until second submission
        assert get_user_pts(db, "sc04_loser") == 1400

    def test_no_point_history_after_first_submission(self, db):
        seed_tier_config(db)
        seed_user(db, "sc04b_winner", pts=1500, tier="amateur")
        seed_user(db, "sc04b_loser", pts=1400, tier="amateur")
        seed_match(db, "sc04b_match", "sc04b_winner", "sc04b_loser")

        svc = make_service(db)
        req = VerifyScoreRequest(winner_uid="sc04b_winner", score=_SCORE)
        svc.verify_score("sc04b_winner", "sc04b_match", req)

        assert get_point_history(db, "sc04b_winner") == []
        assert get_point_history(db, "sc04b_loser") == []


# ---------------------------------------------------------------------------
# SC-05: Walkover — zero deltas, no point history
# ---------------------------------------------------------------------------


class TestWalkover:
    def test_walkover_pts_unchanged(self, db):
        seed_tier_config(db)
        seed_user(db, "sc05_winner", pts=1500, tier="amateur")
        seed_user(db, "sc05_loser", pts=1400, tier="amateur")
        seed_match(db, "sc05_match", "sc05_winner", "sc05_loser")

        svc = make_service(db)
        req = VerifyScoreRequest(winner_uid="sc05_winner", walkover=True)
        svc.verify_score("sc05_winner", "sc05_match", req)
        svc.verify_score("sc05_loser", "sc05_match", req)

        assert get_user_pts(db, "sc05_winner") == 1500
        assert get_user_pts(db, "sc05_loser") == 1400

    def test_walkover_no_point_history_entries(self, db):
        seed_tier_config(db)
        seed_user(db, "sc05b_winner", pts=1500, tier="amateur")
        seed_user(db, "sc05b_loser", pts=1400, tier="amateur")
        seed_match(db, "sc05b_match", "sc05b_winner", "sc05b_loser")

        svc = make_service(db)
        req = VerifyScoreRequest(winner_uid="sc05b_winner", walkover=True)
        svc.verify_score("sc05b_winner", "sc05b_match", req)
        svc.verify_score("sc05b_loser", "sc05b_match", req)

        assert get_point_history(db, "sc05b_winner") == []
        assert get_point_history(db, "sc05b_loser") == []

    def test_walkover_match_status_completed(self, db):
        seed_tier_config(db)
        seed_user(db, "sc05c_winner", pts=1500, tier="amateur")
        seed_user(db, "sc05c_loser", pts=1400, tier="amateur")
        seed_match(db, "sc05c_match", "sc05c_winner", "sc05c_loser")

        svc = make_service(db)
        req = VerifyScoreRequest(winner_uid="sc05c_winner", walkover=True)
        svc.verify_score("sc05c_winner", "sc05c_match", req)
        svc.verify_score("sc05c_loser", "sc05c_match", req)

        assert get_match_status(db, "sc05c_match") == MatchStatusEnum.COMPLETED


# ---------------------------------------------------------------------------
# SC-06: Concurrent confirmation — two matches for the same user simultaneously
# ---------------------------------------------------------------------------


class TestConcurrentConfirmation:
    def test_concurrent_matches_for_same_user_no_lost_updates(self, db):
        """Two matches completing at the same time for the same winner.
        Both transactions should retry and commit; the user ends up with
        pts incremented by exactly 200 (100 per match)."""
        seed_tier_config(db)
        seed_user(db, "sc06_shared", pts=1500, tier="amateur")
        seed_user(db, "sc06_opp_a", pts=1400, tier="amateur")
        seed_user(db, "sc06_opp_b", pts=1300, tier="amateur")
        seed_match(db, "sc06_match_a", "sc06_shared", "sc06_opp_a")
        seed_match(db, "sc06_match_b", "sc06_shared", "sc06_opp_b")

        # Both matches are in pending_confirmation state before concurrent second submission.
        svc = make_service(db)
        req_a = VerifyScoreRequest(winner_uid="sc06_shared", score=_SCORE)
        req_b = VerifyScoreRequest(winner_uid="sc06_shared", score=_SCORE)
        svc.verify_score("sc06_shared", "sc06_match_a", req_a)
        svc.verify_score("sc06_shared", "sc06_match_b", req_b)

        errors: list[Exception] = []

        def confirm_a():
            try:
                make_service(db).verify_score("sc06_opp_a", "sc06_match_a", req_a)
            except Exception as e:
                errors.append(e)

        def confirm_b():
            try:
                make_service(db).verify_score("sc06_opp_b", "sc06_match_b", req_b)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=confirm_a)
        t2 = threading.Thread(target=confirm_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Concurrent confirmation raised: {errors}"

        final_pts = get_user_pts(db, "sc06_shared")
        assert final_pts == 1700  # 1500 + 100 + 100


# ---------------------------------------------------------------------------
# SC-07: Upset during match confirmation writes ticker event
# ---------------------------------------------------------------------------


def _make_service_with_ticker(db) -> MatchConfirmationService:
    return MatchConfirmationService(
        matches_repo=MatchesRepo(db),
        users_repo=UsersRepo(db),
        point_history_repo=PointHistoryRepo(db),
        tier_config_repo=TierConfigRepo(db),
        firestore_client=db,
        ticker_repo=TickerRepo(db),
        region_config_repo=RegionConfigRepo(db),
    )


def _seed_user_with_area(
    db,
    uid: str,
    pts: int,
    tier: str,
    area: int,
    sport: str = "tennis",
) -> None:
    db.collection("users").document(uid).set(
        {
            "name": uid,
            "email": f"{uid}@test.com",
            "rankings": {
                sport: {
                    "sport": sport,
                    "pts": pts,
                    "tier": tier,
                    "registrationTier": tier,
                    "globalRanking": None,
                    "lastUpdated": None,
                }
            },
            "preferences": {
                "area": area,
                "levels": {},
                "sports": [sport],
            },
            "playTab": {
                "state": "MATCH_SCHEDULED",
                "activeMatchId": None,
                "updatedAt": None,
            },
        }
    )


def _get_ticker_events(
    db,
    region: str = "athens",
    sport: str = "tennis",
    event_type: str | None = None,
) -> list[dict]:
    docs = (
        db.collection("ticker")
        .where("region", "==", region)
        .where("sport", "==", sport)
        .stream()
    )
    events = [d.to_dict() or {} for d in docs]
    if event_type is not None:
        return [event for event in events if event.get("type") == event_type]
    return events


class TestUpsetTickerCreation:
    @pytest.fixture(autouse=True)
    def _reset_region_cache(self):
        region_config_module._cache = None
        region_config_module._cache_ts = 0.0
        yield
        region_config_module._cache = None
        region_config_module._cache_ts = 0.0

    @pytest.fixture(autouse=True)
    def _cleanup_ticker_and_config(self, db):
        # Pre-test: wipe any ticker docs left over from previous tests or seeding
        for doc in db.collection("ticker").stream():
            doc.reference.delete()
        yield
        for doc in db.collection("ticker").stream():
            doc.reference.delete()
        db.collection("config").document("regions").delete()

    def test_upset_confirmation_creates_ticker_event(self, db) -> None:
        seed_tier_config(db)
        db.collection("config").document("regions").set(
            {"mapping": {"101": "athens"}, "version": 1}
        )
        _seed_user_with_area(db, "sc07_winner", pts=1800, tier="amateur", area=101)
        _seed_user_with_area(db, "sc07_loser", pts=2200, tier="intermediate", area=101)
        seed_match(db, "sc07_match", "sc07_winner", "sc07_loser")

        svc = _make_service_with_ticker(db)
        req = VerifyScoreRequest(winner_uid="sc07_winner", score=_SCORE)
        svc.verify_score("sc07_winner", "sc07_match", req)
        svc.verify_score("sc07_loser", "sc07_match", req)

        events = _get_ticker_events(db, event_type="upset")
        assert len(events) == 1
        event = events[0]
        assert event["type"] == "upset"
        assert event["sport"] == "tennis"
        assert event["region"] == "athens"
        assert event["winnerUid"] == "sc07_winner"
        assert event["winnerName"] == "sc07_winner"
        assert event["loserTier"] == "intermediate"
        assert event["delta"] > 0

    def test_same_tier_match_no_ticker_event(self, db) -> None:
        seed_tier_config(db)
        db.collection("config").document("regions").set(
            {"mapping": {"101": "athens"}, "version": 1}
        )
        _seed_user_with_area(db, "sc07b_winner", pts=1500, tier="amateur", area=101)
        _seed_user_with_area(db, "sc07b_loser", pts=1400, tier="amateur", area=101)
        seed_match(db, "sc07b_match", "sc07b_winner", "sc07b_loser")

        svc = _make_service_with_ticker(db)
        req = VerifyScoreRequest(winner_uid="sc07b_winner", score=_SCORE)
        svc.verify_score("sc07b_winner", "sc07b_match", req)
        svc.verify_score("sc07b_loser", "sc07b_match", req)

        events = _get_ticker_events(db, event_type="upset")
        assert len(events) == 0

    def test_walkover_does_not_create_ticker_event(self, db) -> None:
        seed_tier_config(db)
        db.collection("config").document("regions").set(
            {"mapping": {"101": "athens"}, "version": 1}
        )
        _seed_user_with_area(db, "sc07c_winner", pts=1800, tier="amateur", area=101)
        _seed_user_with_area(db, "sc07c_loser", pts=2200, tier="intermediate", area=101)
        seed_match(db, "sc07c_match", "sc07c_winner", "sc07c_loser")

        svc = _make_service_with_ticker(db)
        req = VerifyScoreRequest(winner_uid="sc07c_winner", walkover=True)
        svc.verify_score("sc07c_winner", "sc07c_match", req)
        svc.verify_score("sc07c_loser", "sc07c_match", req)

        events = _get_ticker_events(db)
        assert len(events) == 0
