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
_REPORTER_2_UID = "user_reporter_2"
_OPPONENT_UID = "user_opponent"
_MATCH_ID = "match_scouting_test"
_ENTRY_ID = "entry_scouting_test"


@pytest.fixture(autouse=True)
def _cleanup_scouting(db: firestore.Client):
    yield
    for coll_name in ("scouting", "matches"):
        for doc in db.collection(coll_name).stream():
            # Delete subcollections under scouting docs
            if coll_name == "scouting":
                for sub_doc in (
                    db.collection(coll_name)
                    .document(doc.id)
                    .collection("processedReports")
                    .stream()
                ):
                    (
                        db.collection(coll_name)
                        .document(doc.id)
                        .collection("processedReports")
                        .document(sub_doc.id)
                        .delete()
                    )
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


def _get_processed_reports(db: firestore.Client, opponent_uid: str) -> list[dict]:
    """Read all docs from the processedReports subcollection."""
    docs = (
        db.collection("scouting")
        .document(opponent_uid)
        .collection("processedReports")
        .stream()
    )
    return [d.to_dict() or {} for d in docs]


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

    def test_no_raw_uids_in_scouting_doc(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        """Privacy: the main scouting doc must not contain raw reporter UIDs."""
        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id=_ENTRY_ID,
            after={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )
        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
        raw = str(data)
        assert _REPORTER_UID not in raw

    def test_processed_reports_in_subcollection(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        """Dedup state lives in a subcollection, not in the main doc."""
        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id=_ENTRY_ID,
            after={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )
        # Subcollection doc exists
        reports = _get_processed_reports(db, _OPPONENT_UID)
        assert len(reports) == 1
        assert "tagSig" in reports[0]
        assert "reporterHash" in reports[0]

        # Main doc has no processedReports map
        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
        sport_data = data[_SPORT]
        assert "processedReports" not in sport_data

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

    def test_update_applies_diff(self, db: firestore.Client, match_doc: str) -> None:
        """When tags change on the same match+reporter, apply a delta (not re-add)."""
        after_v1 = {
            "sport": _SPORT,
            "matchId": match_doc,
            "reflection": {
                "opponentWeak": ["backhand", "footwork"],
                "opponentStrong": ["serve"],
            },
        }
        handle_scouting_upsert(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, after=after_v1
        )

        # Update: remove footwork, add volley; keep backhand; change serve → net_play
        after_v2 = {
            "sport": _SPORT,
            "matchId": match_doc,
            "reflection": {
                "opponentWeak": ["backhand", "volley"],
                "opponentStrong": ["net_play"],
            },
        }
        changed = handle_scouting_upsert(
            client=db, uid=_REPORTER_UID, entry_id=_ENTRY_ID, after=after_v2
        )

        assert changed is True
        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
        sport_data = data[_SPORT]

        # backhand: kept (count stays 1)
        assert sport_data["weak"]["backhand"]["count"] == 1
        # footwork: removed (should be gone)
        assert "footwork" not in sport_data["weak"]
        # volley: added (count 1)
        assert sport_data["weak"]["volley"]["count"] == 1
        # serve: removed
        assert "serve" not in sport_data["strong"]
        # net_play: added
        assert sport_data["strong"]["net_play"]["count"] == 1

        # totalReports stays 1 (same match+reporter, just updated)
        assert sport_data["totalReports"] == 1
        assert sport_data["uniqueReporters"] == 1

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
        # Same reporter for both matches → uniqueReporters = 1
        assert data[_SPORT]["uniqueReporters"] == 1

    def test_unique_reporters_counts_distinct_users(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        """uniqueReporters counts distinct reporter UIDs, not total reports."""
        # Seed a second match with reporter_2
        match2_id = "match_scouting_test_2"
        db.collection("matches").document(match2_id).set(
            {
                "sport": _SPORT,
                "status": "completed",
                "participantUids": [_REPORTER_2_UID, _OPPONENT_UID],
            }
        )

        # Reporter 1 files a report
        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id="e1",
            after={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )

        # Reporter 2 files a report
        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_2_UID,
            entry_id="e2",
            after={
                "sport": _SPORT,
                "matchId": match2_id,
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )

        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
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

        # Subcollection doc should be gone
        reports = _get_processed_reports(db, _OPPONENT_UID)
        assert len(reports) == 0

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

    def test_delete_preserves_other_reporters(
        self, db: firestore.Client, match_doc: str
    ) -> None:
        """Deleting one reporter's report preserves the other reporter's data."""
        match2_id = "match_scouting_test_2"
        db.collection("matches").document(match2_id).set(
            {
                "sport": _SPORT,
                "status": "completed",
                "participantUids": [_REPORTER_2_UID, _OPPONENT_UID],
            }
        )

        # Reporter 1
        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_UID,
            entry_id="e1",
            after={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )
        # Reporter 2
        handle_scouting_upsert(
            client=db,
            uid=_REPORTER_2_UID,
            entry_id="e2",
            after={
                "sport": _SPORT,
                "matchId": match2_id,
                "reflection": {"opponentWeak": ["backhand", "volley"]},
            },
        )

        # Delete reporter 1's report
        handle_scouting_delete(
            client=db,
            uid=_REPORTER_UID,
            entry_id="e1",
            before={
                "sport": _SPORT,
                "matchId": match_doc,
                "reflection": {"opponentWeak": ["backhand"]},
            },
        )

        data = _get_scouting_data(db, _OPPONENT_UID)
        assert data is not None
        sport_data = data[_SPORT]
        assert sport_data["weak"]["backhand"]["count"] == 1
        assert sport_data["weak"]["volley"]["count"] == 1
        assert sport_data["totalReports"] == 1
        assert sport_data["uniqueReporters"] == 1
