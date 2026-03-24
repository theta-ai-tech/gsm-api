"""
Integration tests for GET /me/lab/ticker.

Seeds ticker events, user, and region config documents into the Firestore emulator,
then calls the endpoint via FastAPI's TestClient to verify all acceptance criteria.

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via `make emu-firestore`)

Run:
    make test-int
    # or just this file:
    pytest tests/integration/test_ticker_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import (
    get_region_config_repo,
    get_ticker_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.main import app
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MY_UID = "ticker_test_user"
_NOW = datetime.now(tz=timezone.utc)
_FUTURE = _NOW + timedelta(days=30)
_PAST = _NOW - timedelta(days=1)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_ticker_event(
    db,
    doc_id: str,
    *,
    region: str = "athens",
    sport: str = "tennis",
    event_type: str = "upset",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> None:
    doc_data: dict = {
        "type": event_type,
        "sport": sport,
        "region": region,
        "createdAt": created_at or _NOW,
        "expiresAt": expires_at or _FUTURE,
    }
    if event_type == "upset":
        doc_data.update(
            winnerUid="u1",
            winnerName="Dana",
            loserTier="advanced",
            delta=200,
        )
    elif event_type == "win_streak":
        doc_data.update(
            userUid="u2",
            userName="Alex",
            streak=5,
        )
    elif event_type == "personal_best":
        doc_data.update(
            userUid="u3",
            userName="Ben",
            newPts=1500,
            previousBest=1200,
        )
    db.collection("ticker").document(doc_id).set(doc_data)


def _seed_user(db, uid: str, area: int = 101) -> None:
    db.collection("users").document(uid).set(
        {
            "uid": uid,
            "name": "Test User",
            "email": "test@example.com",
            "rankings": {},
            "preferences": {
                "area": area,
                "levels": {},
                "sports": [],
            },
        }
    )


def _seed_region_config(db) -> None:
    db.collection("config").document("regions").set(
        {
            "mapping": {"101": "athens", "202": "thessaloniki"},
            "version": 1,
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TICKER_DOC_IDS = [
    "test_upset_1",
    "test_upset_2",
    "test_streak_1",
    "test_pb_1",
    "test_expired_1",
    "test_padel_1",
    "test_london_1",
    # Globally-seeded ticker events from tools/seed_data.py that leak across tests
    "ticker_upset_1",
    "ticker_streak_1",
    "ticker_pb_1",
]


@pytest.fixture(autouse=True)
def _cleanup_ticker(db):
    yield
    for doc_id in _TICKER_DOC_IDS:
        db.collection("ticker").document(doc_id).delete()
    for uid in (_MY_UID,):
        db.collection("users").document(uid).delete()
    db.collection("config").document("regions").delete()


@pytest.fixture
def ticker_client(db):
    mock_user = CurrentUser(uid=_MY_UID, email="me@test.com")
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_ticker_repo] = lambda: TickerRepo(db)
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
    app.dependency_overrides[get_region_config_repo] = lambda: RegionConfigRepo(db)
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# TK-01: Basic response shape with explicit region
# ---------------------------------------------------------------------------


class TestTickerShape:
    def test_returns_200_with_explicit_region(self, ticker_client, db) -> None:
        _seed_ticker_event(db, "test_upset_1")

        resp = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens")

        assert resp.status_code == 200

    def test_top_level_fields_present(self, ticker_client, db) -> None:
        _seed_ticker_event(db, "test_upset_1")

        body = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens").json()

        assert body["region"] == "athens"
        assert body["sport"] == "tennis"
        assert isinstance(body["events"], list)
        assert len(body["events"]) == 1

    def test_upset_event_fields(self, ticker_client, db) -> None:
        _seed_ticker_event(db, "test_upset_1")

        body = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens").json()

        event = body["events"][0]
        assert event["type"] == "upset"
        assert event["sport"] == "tennis"
        assert event["winner_name"] == "Dana"
        assert event["loser_tier"] == "advanced"
        assert event["delta"] == 200
        assert event["created_at"] is not None
        assert event["expires_at"] is not None


# ---------------------------------------------------------------------------
# TK-02: Filtering
# ---------------------------------------------------------------------------


class TestTickerFiltering:
    def test_filters_by_sport(self, ticker_client, db) -> None:
        _seed_ticker_event(db, "test_upset_1", sport="tennis")
        _seed_ticker_event(db, "test_padel_1", sport="padel")

        body = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens").json()

        assert len(body["events"]) == 1
        assert body["events"][0]["sport"] == "tennis"

    def test_filters_by_region(self, ticker_client, db) -> None:
        _seed_ticker_event(db, "test_upset_1", region="athens")
        _seed_ticker_event(db, "test_london_1", region="london")

        body = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens").json()

        assert len(body["events"]) == 1

    def test_excludes_expired_events(self, ticker_client, db) -> None:
        _seed_ticker_event(db, "test_upset_1", expires_at=_FUTURE)
        _seed_ticker_event(db, "test_expired_1", expires_at=_PAST)

        body = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens").json()

        assert len(body["events"]) == 1

    def test_limit_param_respected(self, ticker_client, db) -> None:
        _seed_ticker_event(db, "test_upset_1", created_at=_NOW - timedelta(hours=1))
        _seed_ticker_event(db, "test_upset_2", created_at=_NOW - timedelta(hours=2))

        body = ticker_client.get(
            "/me/lab/ticker?sport=tennis&region=athens&limit=1"
        ).json()

        assert len(body["events"]) == 1


# ---------------------------------------------------------------------------
# TK-03: Region defaulting from user preferences
# ---------------------------------------------------------------------------


class TestTickerRegionDefaulting:
    def test_defaults_region_from_user_area(self, ticker_client, db) -> None:
        _seed_user(db, _MY_UID, area=101)
        _seed_region_config(db)
        _seed_ticker_event(db, "test_upset_1")

        resp = ticker_client.get("/me/lab/ticker?sport=tennis")

        assert resp.status_code == 200
        assert resp.json()["region"] == "athens"


# ---------------------------------------------------------------------------
# TK-04: Error cases
# ---------------------------------------------------------------------------


class TestTickerErrors:
    def test_missing_token_returns_401(self) -> None:
        resp = TestClient(app).get("/me/lab/ticker?sport=tennis&region=athens")

        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, ticker_client) -> None:
        resp = ticker_client.get("/me/lab/ticker?sport=badminton&region=athens")

        assert resp.status_code == 422

    def test_sport_required_returns_422(self, ticker_client) -> None:
        resp = ticker_client.get("/me/lab/ticker?region=athens")

        assert resp.status_code == 422

    def test_limit_over_max_returns_422(self, ticker_client) -> None:
        resp = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens&limit=100")

        assert resp.status_code == 422

    def test_user_not_found_for_default_region_returns_404(self, ticker_client) -> None:
        resp = ticker_client.get("/me/lab/ticker?sport=tennis")

        assert resp.status_code == 404

    def test_empty_events_returns_200(self, ticker_client) -> None:
        resp = ticker_client.get("/me/lab/ticker?sport=tennis&region=athens")

        assert resp.status_code == 200
        assert resp.json()["events"] == []
