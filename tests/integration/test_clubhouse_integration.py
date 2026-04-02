"""
Integration tests for CH-8: match confirmation with streak + personal best updates.

Verifies that the MatchConfirmationService transaction correctly writes
currentStreak, bestStreak, and personalBest fields on users/{uid}.rankings.{sport}
for both winner and loser across multiple match scenarios.

Requires: FIRESTORE_EMULATOR_HOST env var set (e.g. via `make emu-all`)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.repos.tier_config_repo as tier_config_module
from app.models.common import MatchScore, SetScore
from app.models.enums import MatchStatusEnum, SportEnum
from app.models.match import VerifyScoreRequest
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
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

_SCORE_7_5 = MatchScore(
    sets=[SetScore(p1_games=7, p2_games=5)],
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
    current_streak: int = 0,
    best_streak: int = 0,
    personal_best: int | None = None,
) -> None:
    ranking: dict = {
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
    db.collection("users").document(uid).set(
        {
            "name": uid,
            "email": f"{uid}@test.com",
            "rankings": {sport: ranking},
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


def confirm_match(
    db,
    match_id: str,
    winner_uid: str,
    loser_uid: str,
    score: MatchScore = _SCORE_6_3,
    walkover: bool = False,
) -> None:
    """Run the full two-step confirmation flow."""
    svc = make_service(db)
    req = VerifyScoreRequest(winner_uid=winner_uid, score=score, walkover=walkover)
    svc.verify_score(winner_uid, match_id, req)
    svc.verify_score(loser_uid, match_id, req)


def get_ranking(db, uid: str, sport: str = "tennis") -> dict:
    doc = db.collection("users").document(uid).get().to_dict() or {}
    return (doc.get("rankings") or {}).get(sport, {})


def get_streak_fields(db, uid: str, sport: str = "tennis") -> dict:
    ranking = get_ranking(db, uid, sport)
    return {
        "currentStreak": ranking.get("currentStreak", 0),
        "bestStreak": ranking.get("bestStreak", 0),
        "personalBest": ranking.get("personalBest"),
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tier_cache():
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0
    yield
    tier_config_module._cache = None
    tier_config_module._cache_ts = 0.0


@pytest.fixture(autouse=True)
def _cleanup_collections(db):
    yield
    for doc in db.collection("matches").stream():
        doc.reference.delete()
    for doc in db.collection("users").stream():
        for ph in doc.reference.collection("pointHistory").stream():
            ph.reference.delete()
        doc.reference.delete()
    db.collection("config").document("tiers").delete()


# ---------------------------------------------------------------------------
# CH-01: First match win — personalBest set, currentStreak=1, bestStreak=1
# ---------------------------------------------------------------------------


class TestFirstMatchWin:
    def test_winner_streak_set_to_one(self, db):
        seed_tier_config(db)
        seed_user(db, "ch01_winner", pts=1500)
        seed_user(db, "ch01_loser", pts=1400)
        seed_match(db, "ch01_match", "ch01_winner", "ch01_loser")

        confirm_match(db, "ch01_match", "ch01_winner", "ch01_loser")

        fields = get_streak_fields(db, "ch01_winner")
        assert fields["currentStreak"] == 1
        assert fields["bestStreak"] == 1

    def test_winner_personal_best_set(self, db):
        seed_tier_config(db)
        seed_user(db, "ch01b_winner", pts=1500)
        seed_user(db, "ch01b_loser", pts=1400)
        seed_match(db, "ch01b_match", "ch01b_winner", "ch01b_loser")

        confirm_match(db, "ch01b_match", "ch01b_winner", "ch01b_loser")

        fields = get_streak_fields(db, "ch01b_winner")
        # Winner starts at 1500, gains 100 base = 1600
        assert fields["personalBest"] == 1600

    def test_loser_streak_is_zero(self, db):
        seed_tier_config(db)
        seed_user(db, "ch01c_winner", pts=1500)
        seed_user(db, "ch01c_loser", pts=1400)
        seed_match(db, "ch01c_match", "ch01c_winner", "ch01c_loser")

        confirm_match(db, "ch01c_match", "ch01c_winner", "ch01c_loser")

        fields = get_streak_fields(db, "ch01c_loser")
        assert fields["currentStreak"] == 0
        assert fields["bestStreak"] == 0


# ---------------------------------------------------------------------------
# CH-02: Second consecutive win — currentStreak=2, bestStreak=2, PB updated
# ---------------------------------------------------------------------------


class TestSecondConsecutiveWin:
    def test_streak_increments_to_two(self, db):
        seed_tier_config(db)
        # Winner already has streak=1, bestStreak=1, personalBest=1600 from a prior win
        seed_user(
            db,
            "ch02_winner",
            pts=1600,
            current_streak=1,
            best_streak=1,
            personal_best=1600,
        )
        seed_user(db, "ch02_loser", pts=1400)
        seed_match(db, "ch02_match", "ch02_winner", "ch02_loser")

        confirm_match(db, "ch02_match", "ch02_winner", "ch02_loser")

        fields = get_streak_fields(db, "ch02_winner")
        assert fields["currentStreak"] == 2
        assert fields["bestStreak"] == 2

    def test_personal_best_updated_when_pts_higher(self, db):
        seed_tier_config(db)
        seed_user(
            db,
            "ch02b_winner",
            pts=1600,
            current_streak=1,
            best_streak=1,
            personal_best=1600,
        )
        seed_user(db, "ch02b_loser", pts=1400)
        seed_match(db, "ch02b_match", "ch02b_winner", "ch02b_loser")

        confirm_match(db, "ch02b_match", "ch02b_winner", "ch02b_loser")

        fields = get_streak_fields(db, "ch02b_winner")
        # 1600 + 100 base = 1700, which is higher than previous PB of 1600
        assert fields["personalBest"] == 1700

    def test_loser_streak_reset_to_zero(self, db):
        seed_tier_config(db)
        seed_user(
            db,
            "ch02c_winner",
            pts=1600,
            current_streak=1,
            best_streak=1,
            personal_best=1600,
        )
        # Loser had a streak of 3 going in
        seed_user(db, "ch02c_loser", pts=1400, current_streak=3, best_streak=3)
        seed_match(db, "ch02c_match", "ch02c_winner", "ch02c_loser")

        confirm_match(db, "ch02c_match", "ch02c_winner", "ch02c_loser")

        fields = get_streak_fields(db, "ch02c_loser")
        assert fields["currentStreak"] == 0
        assert fields["bestStreak"] == 3  # best streak preserved


# ---------------------------------------------------------------------------
# CH-03: Loss after streak — currentStreak reset, bestStreak unchanged, PB unchanged
# ---------------------------------------------------------------------------


class TestLossAfterStreak:
    def test_current_streak_reset_to_zero(self, db):
        seed_tier_config(db)
        # Loser had a 5-win streak
        seed_user(
            db,
            "ch03_loser",
            pts=1800,
            current_streak=5,
            best_streak=5,
            personal_best=1800,
        )
        seed_user(db, "ch03_winner", pts=1500)
        seed_match(db, "ch03_match", "ch03_winner", "ch03_loser")

        confirm_match(db, "ch03_match", "ch03_winner", "ch03_loser")

        fields = get_streak_fields(db, "ch03_loser")
        assert fields["currentStreak"] == 0

    def test_best_streak_unchanged(self, db):
        seed_tier_config(db)
        seed_user(
            db,
            "ch03b_loser",
            pts=1800,
            current_streak=5,
            best_streak=5,
            personal_best=1800,
        )
        seed_user(db, "ch03b_winner", pts=1500)
        seed_match(db, "ch03b_match", "ch03b_winner", "ch03b_loser")

        confirm_match(db, "ch03b_match", "ch03b_winner", "ch03b_loser")

        fields = get_streak_fields(db, "ch03b_loser")
        assert fields["bestStreak"] == 5

    def test_personal_best_unchanged(self, db):
        seed_tier_config(db)
        seed_user(
            db,
            "ch03c_loser",
            pts=1800,
            current_streak=5,
            best_streak=5,
            personal_best=1900,
        )
        seed_user(db, "ch03c_winner", pts=1500)
        seed_match(db, "ch03c_match", "ch03c_winner", "ch03c_loser")

        confirm_match(db, "ch03c_match", "ch03c_winner", "ch03c_loser")

        # Loser's personal best should not change (no PB update logic on loss)
        # The loser's personalBest field is not touched by the transaction
        ranking = get_ranking(db, "ch03c_loser")
        assert ranking.get("personalBest") == 1900


# ---------------------------------------------------------------------------
# CH-04: Win after loss — currentStreak=1 (fresh start)
# ---------------------------------------------------------------------------


class TestWinAfterLoss:
    def test_fresh_streak_starts_at_one(self, db):
        seed_tier_config(db)
        # Winner previously lost, so currentStreak=0
        seed_user(
            db,
            "ch04_winner",
            pts=1500,
            current_streak=0,
            best_streak=3,
            personal_best=1600,
        )
        seed_user(db, "ch04_loser", pts=1400)
        seed_match(db, "ch04_match", "ch04_winner", "ch04_loser")

        confirm_match(db, "ch04_match", "ch04_winner", "ch04_loser")

        fields = get_streak_fields(db, "ch04_winner")
        assert fields["currentStreak"] == 1

    def test_best_streak_preserved(self, db):
        seed_tier_config(db)
        seed_user(
            db,
            "ch04b_winner",
            pts=1500,
            current_streak=0,
            best_streak=3,
            personal_best=1600,
        )
        seed_user(db, "ch04b_loser", pts=1400)
        seed_match(db, "ch04b_match", "ch04b_winner", "ch04b_loser")

        confirm_match(db, "ch04b_match", "ch04b_winner", "ch04b_loser")

        fields = get_streak_fields(db, "ch04b_winner")
        # bestStreak was 3, new currentStreak is 1 — best stays 3
        assert fields["bestStreak"] == 3

    def test_personal_best_updated_if_pts_higher(self, db):
        seed_tier_config(db)
        # Winner at 1500 with PB of 1450 — a win (+100) gives 1600 > 1450
        seed_user(
            db,
            "ch04c_winner",
            pts=1500,
            current_streak=0,
            best_streak=3,
            personal_best=1450,
        )
        seed_user(db, "ch04c_loser", pts=1400)
        seed_match(db, "ch04c_match", "ch04c_winner", "ch04c_loser")

        confirm_match(db, "ch04c_match", "ch04c_winner", "ch04c_loser")

        fields = get_streak_fields(db, "ch04c_winner")
        assert fields["personalBest"] == 1600

    def test_personal_best_not_updated_if_pts_lower(self, db):
        seed_tier_config(db)
        # Winner at 1500 with PB of 1800 — a win gives 1600 < 1800
        seed_user(
            db,
            "ch04d_winner",
            pts=1500,
            current_streak=0,
            best_streak=3,
            personal_best=1800,
        )
        seed_user(db, "ch04d_loser", pts=1400)
        seed_match(db, "ch04d_match", "ch04d_winner", "ch04d_loser")

        confirm_match(db, "ch04d_match", "ch04d_winner", "ch04d_loser")

        fields = get_streak_fields(db, "ch04d_winner")
        assert fields["personalBest"] == 1800


# ---------------------------------------------------------------------------
# CH-05: Upset win with personal best — PB updated with large pts jump
# ---------------------------------------------------------------------------


class TestUpsetWinWithPersonalBest:
    def test_upset_winner_personal_best_updated(self, db):
        seed_tier_config(db)
        # Amateur beats intermediate: base(100) + upset(50) + elo(floor(400*0.05)=20) = 170
        seed_user(
            db,
            "ch05_winner",
            pts=1800,
            current_streak=0,
            best_streak=0,
            personal_best=1800,
        )
        seed_user(db, "ch05_loser", pts=2200, tier="intermediate")
        seed_match(db, "ch05_match", "ch05_winner", "ch05_loser")

        confirm_match(db, "ch05_match", "ch05_winner", "ch05_loser")

        fields = get_streak_fields(db, "ch05_winner")
        # 1800 + 170 = 1970
        assert fields["personalBest"] == 1970

    def test_upset_winner_streak_increments(self, db):
        seed_tier_config(db)
        seed_user(
            db,
            "ch05b_winner",
            pts=1800,
            current_streak=2,
            best_streak=2,
            personal_best=1800,
        )
        seed_user(db, "ch05b_loser", pts=2200, tier="intermediate")
        seed_match(db, "ch05b_match", "ch05b_winner", "ch05b_loser")

        confirm_match(db, "ch05b_match", "ch05b_winner", "ch05b_loser")

        fields = get_streak_fields(db, "ch05b_winner")
        assert fields["currentStreak"] == 3
        assert fields["bestStreak"] == 3

    def test_upset_loser_streak_reset(self, db):
        seed_tier_config(db)
        seed_user(db, "ch05c_winner", pts=1800)
        seed_user(
            db,
            "ch05c_loser",
            pts=2200,
            tier="intermediate",
            current_streak=4,
            best_streak=7,
        )
        seed_match(db, "ch05c_match", "ch05c_winner", "ch05c_loser")

        confirm_match(db, "ch05c_match", "ch05c_winner", "ch05c_loser")

        fields = get_streak_fields(db, "ch05c_loser")
        assert fields["currentStreak"] == 0
        assert fields["bestStreak"] == 7


# ---------------------------------------------------------------------------
# CH-06: Walkover — no streak or personalBest changes
# ---------------------------------------------------------------------------


class TestWalkoverNoStreakChanges:
    def test_walkover_winner_streak_unchanged(self, db):
        seed_tier_config(db)
        seed_user(
            db,
            "ch06_winner",
            pts=1500,
            current_streak=3,
            best_streak=5,
            personal_best=1600,
        )
        seed_user(db, "ch06_loser", pts=1400)
        seed_match(db, "ch06_match", "ch06_winner", "ch06_loser")

        confirm_match(db, "ch06_match", "ch06_winner", "ch06_loser", walkover=True)

        fields = get_streak_fields(db, "ch06_winner")
        assert fields["currentStreak"] == 3
        assert fields["bestStreak"] == 5
        assert fields["personalBest"] == 1600

    def test_walkover_loser_streak_unchanged(self, db):
        seed_tier_config(db)
        seed_user(db, "ch06b_winner", pts=1500)
        seed_user(
            db,
            "ch06b_loser",
            pts=1400,
            current_streak=2,
            best_streak=4,
            personal_best=1500,
        )
        seed_match(db, "ch06b_match", "ch06b_winner", "ch06b_loser")

        confirm_match(db, "ch06b_match", "ch06b_winner", "ch06b_loser", walkover=True)

        fields = get_streak_fields(db, "ch06b_loser")
        assert fields["currentStreak"] == 2
        assert fields["bestStreak"] == 4
        assert fields["personalBest"] == 1500

    def test_walkover_winner_pts_unchanged(self, db):
        seed_tier_config(db)
        seed_user(db, "ch06c_winner", pts=1500)
        seed_user(db, "ch06c_loser", pts=1400)
        seed_match(db, "ch06c_match", "ch06c_winner", "ch06c_loser")

        confirm_match(db, "ch06c_match", "ch06c_winner", "ch06c_loser", walkover=True)

        ranking = get_ranking(db, "ch06c_winner")
        assert ranking["pts"] == 1500

    def test_walkover_match_status_completed(self, db):
        seed_tier_config(db)
        seed_user(db, "ch06d_winner", pts=1500)
        seed_user(db, "ch06d_loser", pts=1400)
        seed_match(db, "ch06d_match", "ch06d_winner", "ch06d_loser")

        confirm_match(db, "ch06d_match", "ch06d_winner", "ch06d_loser", walkover=True)

        doc = db.collection("matches").document("ch06d_match").get().to_dict() or {}
        assert doc["status"] == MatchStatusEnum.COMPLETED
