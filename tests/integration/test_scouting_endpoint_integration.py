"""
Integration tests for GET /me/lab/scouting/{opponentUid}.

Seeds scouting documents directly into the Firestore emulator, then calls the
endpoint via FastAPI's TestClient to verify all acceptance criteria.

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via `make emu-firestore`)

Run:
    make test-int
    # or just this file:
    pytest tests/integration/test_scouting_endpoint_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_scouting_repo
from app.deps import get_current_user
from app.main import app
from app.repos.scouting_repo import ScoutingRepo
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MY_UID = "scouting_me"
_OPP_UID = "scouting_opp"
_NOW = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_scouting_doc(
    db,
    uid: str,
    *,
    sport: str = "tennis",
    weak: dict | None = None,
    strong: dict | None = None,
    total_reports: int = 12,
    unique_reporters: int = 8,
) -> None:
    weak = weak or {
        "backhand": {"count": 7, "lastReported": _NOW},
        "stamina_set3": {"count": 3, "lastReported": _NOW},
    }
    strong = strong or {
        "first_serve": {"count": 5, "lastReported": _NOW},
    }
    db.collection("scouting").document(uid).set(
        {
            "uid": uid,
            sport: {
                "weak": weak,
                "strong": strong,
                "totalReports": total_reports,
                "uniqueReporters": unique_reporters,
                "lastUpdated": _NOW,
            },
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_scouting(db):
    yield
    for uid in (_OPP_UID, "scouting_low", "scouting_medium"):
        db.collection("scouting").document(uid).delete()


@pytest.fixture
def scouting_client(db):
    mock_user = CurrentUser(uid=_MY_UID, email="me@test.com")
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_scouting_repo] = lambda: ScoutingRepo(db)
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# SC-01: Basic response shape
# ---------------------------------------------------------------------------


class TestScoutingShape:
    def test_returns_200(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID)

        resp = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis")

        assert resp.status_code == 200

    def test_top_level_fields_present(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID)

        body = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis").json()

        assert body["uid"] == _OPP_UID
        assert body["sport"] == "tennis"
        assert body["total_reports"] == 12
        assert body["unique_reporters"] == 8
        assert body["last_updated"] is not None
        assert body["confidence"] == "high"

    def test_weak_tags_sorted_descending(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID)

        body = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis").json()

        weak = body["weak"]
        assert len(weak) == 2
        assert weak[0]["tag"] == "backhand"
        assert weak[0]["count"] == 7
        assert weak[0]["label"] == "Backhand"
        assert weak[1]["tag"] == "stamina_set3"
        assert weak[1]["count"] == 3
        assert weak[1]["label"] == "Late-set stamina"

    def test_strong_tags_present(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID)

        body = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis").json()

        strong = body["strong"]
        assert len(strong) == 1
        assert strong[0]["tag"] == "first_serve"
        assert strong[0]["count"] == 5
        assert strong[0]["label"] == "First serve"


# ---------------------------------------------------------------------------
# SC-02: Confidence levels
# ---------------------------------------------------------------------------


class TestConfidenceLevels:
    def test_low_confidence(self, scouting_client, db) -> None:
        _seed_scouting_doc(
            db,
            _OPP_UID,
            total_reports=2,
            unique_reporters=2,
            weak={"backhand": {"count": 2, "lastReported": _NOW}},
            strong={},
        )

        body = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis").json()

        assert body["confidence"] == "low"

    def test_medium_confidence_at_boundary(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID, total_reports=3, unique_reporters=3)

        body = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis").json()

        assert body["confidence"] == "medium"

    def test_medium_confidence_at_upper_boundary(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID, total_reports=7, unique_reporters=5)

        body = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis").json()

        assert body["confidence"] == "medium"

    def test_high_confidence(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID, total_reports=8, unique_reporters=6)

        body = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis").json()

        assert body["confidence"] == "high"


# ---------------------------------------------------------------------------
# SC-03: Error cases
# ---------------------------------------------------------------------------


class TestScoutingErrors:
    def test_no_scouting_doc_returns_404(self, scouting_client) -> None:
        resp = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis")

        assert resp.status_code == 404

    def test_no_sport_data_returns_404(self, scouting_client, db) -> None:
        _seed_scouting_doc(db, _OPP_UID, sport="padel")

        resp = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis")

        assert resp.status_code == 404

    def test_missing_token_returns_401(self) -> None:
        resp = TestClient(app).get(f"/me/lab/scouting/{_OPP_UID}?sport=tennis")

        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, scouting_client) -> None:
        resp = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}?sport=badminton")

        assert resp.status_code == 422

    def test_sport_required_returns_422(self, scouting_client) -> None:
        resp = scouting_client.get(f"/me/lab/scouting/{_OPP_UID}")

        assert resp.status_code == 422
