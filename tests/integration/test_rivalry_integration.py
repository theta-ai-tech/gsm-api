"""
Integration smoke tests for GET /me/lab/rivalry/{opponentUid}.

Seeds two user profiles and a set of completed matches directly into the
Firestore emulator, then calls the endpoint via FastAPI's TestClient to verify
all acceptance criteria against real data.

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via `make emu-firestore`)

Run:
    make test-int
    # or just this file:
    pytest tests/integration/test_rivalry_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_matches_repo, get_users_repo
from app.deps import get_current_user
from app.main import app
from app.models.enums import SportEnum
from app.models.match import compute_participant_pair
from app.repos.matches_repo import MatchesRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MY_UID = "rivalry_me"
_OPP_UID = "rivalry_opp"
_PAIR = compute_participant_pair([_MY_UID, _OPP_UID])  # deterministic
_SPORT = SportEnum.TENNIS.value

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_user(
    db,
    uid: str,
    *,
    name: str,
    pts: int,
    tier: str,
    skill_dna: dict | None = None,
) -> None:
    doc: dict = {
        "uid": uid,
        "name": name,
        "email": f"{uid}@test.com",
        "rankings": {
            _SPORT: {
                "sport": _SPORT,
                "pts": pts,
                "tier": tier,
                "registrationTier": tier,
                "globalRanking": None,
                "lastUpdated": None,
            }
        },
        "leaguesActive": [],
        "leaguesCompleted": [],
    }
    if skill_dna is not None:
        doc["skillDna"] = skill_dna
    db.collection("users").document(uid).set(doc)


def _seed_match(
    db,
    match_id: str,
    *,
    winner_uid: str,
    loser_uid: str,
    finished_at: datetime,
    sets: list[tuple[int, int]] | None = None,
) -> None:
    loser_uid_resolved = loser_uid
    sets = sets or [(6, 3)]
    db.collection("matches").document(match_id).set(
        {
            "sport": _SPORT,
            "status": "completed",
            "participantUids": [winner_uid, loser_uid_resolved],
            "participantPair": _PAIR,
            "participants": [
                {"uid": winner_uid, "role": "player"},
                {"uid": loser_uid_resolved, "role": "player"},
            ],
            "scheduledAt": finished_at - timedelta(hours=1),
            "finishedAt": finished_at,
            "resultByUser": {
                winner_uid: "W",
                loser_uid_resolved: "L",
            },
            "score": {
                "sets": [{"p1Games": p1, "p2Games": p2} for p1, p2 in sets],
                "winnerUid": winner_uid,
                "retired": False,
            },
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_rivalry(db):
    """Remove rivalry test documents after each test."""
    yield
    for uid in (_MY_UID, _OPP_UID):
        db.collection("users").document(uid).delete()
    for doc in db.collection("matches").stream():
        if doc.id.startswith("rivalry_"):
            doc.reference.delete()


@pytest.fixture
def rivalry_client(db):
    """TestClient with dependency overrides pointing at the Firestore emulator."""
    mock_user = CurrentUser(uid=_MY_UID, email="me@test.com")
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
    app.dependency_overrides[get_matches_repo] = lambda: MatchesRepo(db)
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# RV-01: Basic response shape
# ---------------------------------------------------------------------------


class TestRivalryShape:
    def test_returns_200(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        resp = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis")

        assert resp.status_code == 200

    def test_top_level_fields_present(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["sport"] == "tennis"
        assert "me" in body
        assert "opponent" in body
        assert "win_probability" in body
        assert "head_to_head" in body
        assert "recent_matches" in body

    def test_me_and_opponent_player_info(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["me"]["uid"] == _MY_UID
        assert body["me"]["name"] == "Me"
        assert body["me"]["pts"] == 2000
        assert body["me"]["tier"] == "intermediate"
        assert body["opponent"]["uid"] == _OPP_UID
        assert body["opponent"]["name"] == "Opponent"
        assert body["opponent"]["pts"] == 2500
        assert body["opponent"]["tier"] == "advanced"


# ---------------------------------------------------------------------------
# RV-02: Win probability
# ---------------------------------------------------------------------------


class TestWinProbability:
    def test_lower_pts_yields_probability_below_half(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["win_probability"] < 0.5

    def test_higher_pts_yields_probability_above_half(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2500, tier="advanced")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2000, tier="intermediate")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["win_probability"] > 0.5

    def test_equal_pts_yields_exactly_half(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2000, tier="intermediate")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["win_probability"] == 0.5

    def test_probability_never_zero_or_one(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=100, tier="amateur")
        _seed_user(db, _OPP_UID, name="Opponent", pts=99999, tier="competitive")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["win_probability"] > 0.0
        assert body["win_probability"] < 1.0


# ---------------------------------------------------------------------------
# RV-03: Head-to-head counts
# ---------------------------------------------------------------------------


class TestHeadToHead:
    def test_empty_h2h_when_no_matches(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        h2h = body["head_to_head"]
        assert h2h["my_wins"] == 0
        assert h2h["opponent_wins"] == 0
        assert h2h["total_matches"] == 0

    def test_h2h_counts_my_wins_correctly(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")
        _seed_match(
            db, "rivalry_m1", winner_uid=_MY_UID, loser_uid=_OPP_UID, finished_at=_T0
        )
        _seed_match(
            db,
            "rivalry_m2",
            winner_uid=_MY_UID,
            loser_uid=_OPP_UID,
            finished_at=_T0 - timedelta(days=1),
        )
        _seed_match(
            db,
            "rivalry_m3",
            winner_uid=_OPP_UID,
            loser_uid=_MY_UID,
            finished_at=_T0 - timedelta(days=2),
        )

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        h2h = body["head_to_head"]
        assert h2h["my_wins"] == 2
        assert h2h["opponent_wins"] == 1
        assert h2h["total_matches"] == 3

    def test_h2h_counts_opponent_wins_correctly(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")
        for i in range(4):
            _seed_match(
                db,
                f"rivalry_opp{i}",
                winner_uid=_OPP_UID,
                loser_uid=_MY_UID,
                finished_at=_T0 - timedelta(days=i),
            )

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["head_to_head"]["opponent_wins"] == 4
        assert body["head_to_head"]["my_wins"] == 0


# ---------------------------------------------------------------------------
# RV-04: Recent matches ordering, scoreText and result
# ---------------------------------------------------------------------------


class TestRecentMatches:
    def test_recent_matches_ordered_newest_first(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")
        _seed_match(
            db,
            "rivalry_recent1",
            winner_uid=_MY_UID,
            loser_uid=_OPP_UID,
            finished_at=_T0 - timedelta(days=2),
        )
        _seed_match(
            db,
            "rivalry_recent2",
            winner_uid=_OPP_UID,
            loser_uid=_MY_UID,
            finished_at=_T0 - timedelta(days=1),
        )
        _seed_match(
            db,
            "rivalry_recent3",
            winner_uid=_MY_UID,
            loser_uid=_OPP_UID,
            finished_at=_T0,
        )

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()
        match_ids = [m["match_id"] for m in body["recent_matches"]]

        assert match_ids[0] == "rivalry_recent3"  # newest first
        assert match_ids[1] == "rivalry_recent2"
        assert match_ids[2] == "rivalry_recent1"

    def test_result_w_when_i_won(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")
        _seed_match(
            db, "rivalry_win", winner_uid=_MY_UID, loser_uid=_OPP_UID, finished_at=_T0
        )

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["recent_matches"][0]["result"] == "W"

    def test_result_l_when_i_lost(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")
        _seed_match(
            db, "rivalry_loss", winner_uid=_OPP_UID, loser_uid=_MY_UID, finished_at=_T0
        )

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["recent_matches"][0]["result"] == "L"

    def test_score_text_rendered_correctly(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")
        _seed_match(
            db,
            "rivalry_score",
            winner_uid=_MY_UID,
            loser_uid=_OPP_UID,
            finished_at=_T0,
            sets=[(6, 4), (3, 6), (7, 5)],
        )

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["recent_matches"][0]["score_text"] == "6-4, 3-6, 7-5"

    def test_limit_param_restricts_recent_matches(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")
        for i in range(5):
            _seed_match(
                db,
                f"rivalry_lim{i}",
                winner_uid=_MY_UID,
                loser_uid=_OPP_UID,
                finished_at=_T0 - timedelta(days=i),
            )

        body = rivalry_client.get(
            f"/me/lab/rivalry/{_OPP_UID}?sport=tennis&limit=3"
        ).json()

        assert len(body["recent_matches"]) == 3


# ---------------------------------------------------------------------------
# RV-05: Skill DNA comparison
# ---------------------------------------------------------------------------


class TestSkillDnaComparison:
    def test_null_when_neither_user_has_dna(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["skill_dna_comparison"] is None

    def test_comparison_present_when_i_have_dna(self, rivalry_client, db) -> None:
        my_dna = {
            "tennis": {
                "serve": {"positive": 10, "negative": 2, "score": 83},
                "totalReflections": 12,
            }
        }
        _seed_user(
            db, _MY_UID, name="Me", pts=2000, tier="intermediate", skill_dna=my_dna
        )
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["skill_dna_comparison"] is not None
        assert body["skill_dna_comparison"]["me"]["serve"] == 83

    def test_comparison_shows_both_profiles(self, rivalry_client, db) -> None:
        my_dna = {
            "tennis": {
                "serve": {"positive": 10, "negative": 2, "score": 83},
                "totalReflections": 1,
            }
        }
        opp_dna = {
            "tennis": {
                "serve": {"positive": 7, "negative": 5, "score": 58},
                "totalReflections": 1,
            }
        }
        _seed_user(
            db, _MY_UID, name="Me", pts=2000, tier="intermediate", skill_dna=my_dna
        )
        _seed_user(
            db, _OPP_UID, name="Opponent", pts=2500, tier="advanced", skill_dna=opp_dna
        )

        body = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis").json()

        assert body["skill_dna_comparison"]["me"]["serve"] == 83
        assert body["skill_dna_comparison"]["opponent"]["serve"] == 58


# ---------------------------------------------------------------------------
# RV-06: Error cases
# ---------------------------------------------------------------------------


class TestRivalryErrors:
    def test_opponent_not_found_returns_404(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        # _OPP_UID is NOT seeded

        resp = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis")

        assert resp.status_code == 404
        assert "opponent" in resp.json()["detail"].lower()

    def test_missing_token_returns_401(self) -> None:
        resp = TestClient(app).get(f"/me/lab/rivalry/{_OPP_UID}?sport=tennis")

        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, rivalry_client, db) -> None:
        _seed_user(db, _MY_UID, name="Me", pts=2000, tier="intermediate")
        _seed_user(db, _OPP_UID, name="Opponent", pts=2500, tier="advanced")

        resp = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}?sport=badminton")

        assert resp.status_code == 422

    def test_sport_required_returns_422(self, rivalry_client, db) -> None:
        resp = rivalry_client.get(f"/me/lab/rivalry/{_OPP_UID}")

        assert resp.status_code == 422
