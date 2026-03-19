"""
Integration tests for the MatchesRepo.list_head_to_head() query using the
participantPair field on the Firestore emulator.

Verifies:
- 3 matches between Alice and Bob are all returned
- Query for Alice vs Carol returns 0 (no matches between them)
- Results ordered by finishedAt DESC
- participantPair is consistent regardless of who created the match (lexicographic)

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via `make emu-firestore`)

Run:
    make test-int
    # or just this file:
    pytest tests/integration/test_h2h_query_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from google.cloud import firestore

from app.models.enums import SportEnum
from app.models.match import compute_participant_pair
from app.repos.matches_repo import MatchesRepo

pytestmark = [pytest.mark.integration]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALICE = "h2h_alice"
_BOB = "h2h_bob"
_CAROL = "h2h_carol"
_PAIR_AB = compute_participant_pair([_ALICE, _BOB])
_PAIR_AC = compute_participant_pair([_ALICE, _CAROL])
_SPORT = SportEnum.TENNIS

_T0 = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_match(
    db: firestore.Client,
    match_id: str,
    *,
    winner_uid: str,
    loser_uid: str,
    finished_at: datetime,
    pair: str | None = None,
    sport: str = "tennis",
    status: str = "completed",
) -> None:
    pair = pair or compute_participant_pair([winner_uid, loser_uid])
    db.collection("matches").document(match_id).set(
        {
            "sport": sport,
            "status": status,
            "participantUids": [winner_uid, loser_uid],
            "participantPair": pair,
            "participants": [
                {"uid": winner_uid, "role": "player"},
                {"uid": loser_uid, "role": "player"},
            ],
            "scheduledAt": finished_at - timedelta(hours=1),
            "finishedAt": finished_at,
            "resultByUser": {
                winner_uid: "W",
                loser_uid: "L",
            },
            "score": {
                "sets": [{"p1Games": 6, "p2Games": 3}],
                "winnerUid": winner_uid,
                "retired": False,
            },
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_h2h(db: firestore.Client):
    yield
    for doc in db.collection("matches").stream():
        if doc.id.startswith("h2h_"):
            doc.reference.delete()


@pytest.fixture
def repo(db: firestore.Client) -> MatchesRepo:
    return MatchesRepo(db)


# ---------------------------------------------------------------------------
# H2H-01: Three matches between Alice and Bob are returned
# ---------------------------------------------------------------------------


class TestH2HQueryReturnsMatches:
    def test_three_matches_returned(
        self, db: firestore.Client, repo: MatchesRepo
    ) -> None:
        _seed_match(db, "h2h_m1", winner_uid=_ALICE, loser_uid=_BOB, finished_at=_T0)
        _seed_match(
            db,
            "h2h_m2",
            winner_uid=_BOB,
            loser_uid=_ALICE,
            finished_at=_T0 - timedelta(days=1),
        )
        _seed_match(
            db,
            "h2h_m3",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0 - timedelta(days=2),
        )

        assert _PAIR_AB is not None
        results = repo.list_head_to_head(pair=_PAIR_AB, sport=_SPORT, limit=10)

        assert len(results) == 3


# ---------------------------------------------------------------------------
# H2H-02: Query Alice vs Carol returns 0
# ---------------------------------------------------------------------------


class TestH2HQueryNoMatches:
    def test_no_matches_for_different_pair(
        self, db: firestore.Client, repo: MatchesRepo
    ) -> None:
        _seed_match(db, "h2h_m1", winner_uid=_ALICE, loser_uid=_BOB, finished_at=_T0)
        _seed_match(
            db,
            "h2h_m2",
            winner_uid=_BOB,
            loser_uid=_ALICE,
            finished_at=_T0 - timedelta(days=1),
        )

        assert _PAIR_AC is not None
        results = repo.list_head_to_head(pair=_PAIR_AC, sport=_SPORT, limit=10)

        assert len(results) == 0


# ---------------------------------------------------------------------------
# H2H-03: Results ordered by finishedAt DESC
# ---------------------------------------------------------------------------


class TestH2HOrdering:
    def test_ordered_by_finished_at_descending(
        self, db: firestore.Client, repo: MatchesRepo
    ) -> None:
        _seed_match(
            db,
            "h2h_oldest",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0 - timedelta(days=10),
        )
        _seed_match(
            db,
            "h2h_middle",
            winner_uid=_BOB,
            loser_uid=_ALICE,
            finished_at=_T0 - timedelta(days=5),
        )
        _seed_match(
            db,
            "h2h_newest",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0,
        )

        assert _PAIR_AB is not None
        results = repo.list_head_to_head(pair=_PAIR_AB, sport=_SPORT, limit=10)

        match_ids = [m.match_id for m in results]
        assert match_ids == ["h2h_newest", "h2h_middle", "h2h_oldest"]


# ---------------------------------------------------------------------------
# H2H-04: participantPair is consistent (lexicographic)
# ---------------------------------------------------------------------------


class TestParticipantPairConsistency:
    def test_pair_same_regardless_of_creator_order(
        self, db: firestore.Client, repo: MatchesRepo
    ) -> None:
        pair_alice_first = compute_participant_pair([_ALICE, _BOB])
        pair_bob_first = compute_participant_pair([_BOB, _ALICE])

        assert pair_alice_first == pair_bob_first

        _seed_match(
            db,
            "h2h_alice_created",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0,
            pair=pair_alice_first,
        )
        _seed_match(
            db,
            "h2h_bob_created",
            winner_uid=_BOB,
            loser_uid=_ALICE,
            finished_at=_T0 - timedelta(days=1),
            pair=pair_bob_first,
        )

        assert _PAIR_AB is not None
        results = repo.list_head_to_head(pair=_PAIR_AB, sport=_SPORT, limit=10)

        assert len(results) == 2
        match_ids = {m.match_id for m in results}
        assert match_ids == {"h2h_alice_created", "h2h_bob_created"}

    def test_pair_is_lexicographically_sorted(self) -> None:
        assert compute_participant_pair(["zara", "anna"]) == "anna_zara"
        assert compute_participant_pair(["anna", "zara"]) == "anna_zara"


# ---------------------------------------------------------------------------
# H2H-05: Edge cases — sport and status filtering
# ---------------------------------------------------------------------------


class TestH2HFiltering:
    def test_only_matching_sport_returned(
        self, db: firestore.Client, repo: MatchesRepo
    ) -> None:
        _seed_match(
            db,
            "h2h_tennis",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0,
            sport="tennis",
        )
        _seed_match(
            db,
            "h2h_padel",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0 - timedelta(days=1),
            sport="padel",
        )

        assert _PAIR_AB is not None
        results = repo.list_head_to_head(
            pair=_PAIR_AB, sport=SportEnum.TENNIS, limit=10
        )

        assert len(results) == 1
        assert results[0].match_id == "h2h_tennis"

    def test_only_completed_matches_returned(
        self, db: firestore.Client, repo: MatchesRepo
    ) -> None:
        _seed_match(
            db,
            "h2h_completed",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0,
            status="completed",
        )
        _seed_match(
            db,
            "h2h_scheduled",
            winner_uid=_ALICE,
            loser_uid=_BOB,
            finished_at=_T0 - timedelta(days=1),
            status="scheduled",
        )

        assert _PAIR_AB is not None
        results = repo.list_head_to_head(pair=_PAIR_AB, sport=_SPORT, limit=10)

        assert len(results) == 1
        assert results[0].match_id == "h2h_completed"
