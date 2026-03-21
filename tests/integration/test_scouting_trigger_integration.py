"""Integration tests for the scouting trigger (D4.3/D4.4) against the Firestore emulator."""

from __future__ import annotations

import pytest
from google.cloud import firestore

from functions.journal_triggers.scouting import (
    handle_scouting_delete,
    handle_scouting_upsert,
)

pytestmark = pytest.mark.integration

_SPORT = "tennis"
_REPORTER_UID = "user_reporter"
_OPPONENT_UID = "user_opponent"
_MATCH_ID = "match_scouting_test"
_ENTRY_ID = "entry_scouting_test"


@pytest.fixture(autouse=True)
def _cleanup_scouting(db: firestore.Client):
    yield
    for coll_name in ("scouting", "matches"):
        for doc in db.collection(coll_name).stream():
            db.collection(coll_name).document(doc.id).delete()


@pytest.fixture
def match_doc(db: firestore.Client) -> str:
    """Seed a match document with two participants."""
    db.collection("matches").document(_MATCH_ID).set(
        {
            "sport": _SPORT,
            "status": "completed",
            "participantUids": [_REPORTER_UID, _OPPONENT_UID],
        }
    )
    return _MATCH_ID


def _get_scouting_data(db: firestore.Client, uid: str) -> dict | None:
    snap = db.collection("scouting").document(uid).get()
    if not snap.exists:
        return None
    return snap.to_dict()


class TestScoutingUpsert:
    def test_creates_scouting_profile_on_first_report(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        changed = handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id=_ENTRY_ID,
            after={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {
                    "opponentWeak": ["backhand", "footwork"],
                    "opponentStrong": ["serve"],
                },
            },
        )

        assert changed is True
        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None

        sport_data = data[_SPORT]
        assert sport_data["weak"]["backhand"]["count"] == 1
        assert sport_data["weak"]["footwork"]["count"] == 1
        assert sport_data["strong"]["serve"]["count"] == 1
        assert sport_data["totalReports"] == 1
        assert sport_data["uniqueReporters"] == 1
        assert "lastUpdated" in sport_data

    def test_dedup_prevents_double_counting(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        after = {
            "sport": _SPORT,
            "matchId": match_doc,
            "reflection": {
                "opponentWeak": ["backhand"],
                "opponentStrong": [],
            },
        }

        result1 = handle_scouting_upsert(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, after=after
        )
        result2 = handle_scouting_upsert(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, after=after
        )

        assert result1 is True
        assert result2 is False

        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
        assert data[_SPORT]["weak"]["backhand"]["count"] == 1
        assert data[_SPORT]["totalReports"] == 1

    def test_accumulates_from_multiple_matches(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        # First match report
        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id="e1",
            after={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {"opponentWeak": ["backhand"], "opponentStrong": []},
            },
        )

        # Seed a second match
        match2_id = "match_scouting_test_2"
        db.collection("matches").document(match2_id).set(
            {
                "sport": _SPORT,
                "status": "completed",
                "participantUids": [_REPORTER_UID, _OPPONENT_UID],
            }
        )

        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id="e2",
            after={
                "sport": _SPORT,
                "matchId": match2_id,
                "reflection": {
                    "opponentWeak": ["backhand", "volley"],
                    "opponentStrong": [],
                },
            },
        )

        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
        assert data[_SPORT]["weak"]["backhand"]["count"] == 2
        assert data[_SPORT]["weak"]["volley"]["count"] == 1
        assert data[_SPORT]["totalReports"] == 2
        assert data[_SPORT]["uniqueReporters"] == 2

    def test_ignores_when_no_match_doc(self, db: firestore.Client) -> None:
        result = handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id=_ENTRY_ID,
            after={
                "sport": _SPORT,
                "matchId": "nonexistent_match",
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )
        assert result is False
        assert _get_scouting_data(db, _OPPONENT_UID) is None


class TestScoutingDelete:
    def test_reverses_scouting_report(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        entry_data = {
            "sport": _SPORT,
            "matchId": match_doc,
            "reflection": {
                "opponentWeak": ["backhand"],
                "opponentStrong": ["serve"],
            },
        }

        handle_scouting_upsert(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, after=entry_data
        )

        changed = handle_scouting_delete(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, before=entry_data
        )

        assert changed is True
        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
        sport_data = data[_SPORT]
        assert sport_data["totalReports"] == 0
        assert sport_data["uniqueReporters"] == 0
        # Tags with count 0 are removed
        assert "backhand" not in sport_data.get("weak", {})
        assert "serve" not in sport_data.get("strong", {})

    def test_delete_idempotent_when_not_processed(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        result = handle_scouting_delete(
            client=db,
            uid=_REPORTER_UID,
            entry_id=_ENTRY_ID,
            before={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )
        assert result is False

    def test_delete_idempotent_on_repeat(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        entry_data = {
            "sport": _SPORT,
            "matchId": match_doc,
            "reflection": {"opponentWeak": ["backhand"], "opponentStrong": []},
        }

        handle_scouting_upsert(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, after=entry_data
        )
        r1 = handle_scouting_delete(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, before=entry_data
        )
        r2 = handle_scouting_delete(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, before=entry_data
        )

        assert r1 is True
        assert r2 is False
