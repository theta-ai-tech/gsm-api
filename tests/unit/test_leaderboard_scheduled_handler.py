"""Unit tests for the D7 scheduled leaderboard handler (mocked Firestore)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from functions.scheduled.leaderboard_computation import compute_leaderboards


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


_NOW = _utc(2026, 3, 20, 12)


def _mock_region_doc() -> MagicMock:
    doc = MagicMock()
    doc.exists = True
    doc.to_dict.return_value = {
        "mapping": {"101": "athens", "102": "athens", "202": "thessaloniki"},
        "version": 1,
    }
    return doc


def _mock_user_docs() -> list[MagicMock]:
    users = [
        {
            "uid": "u1",
            "name": "Alice",
            "preferences": {"area": 101},
            "rankings": {
                "tennis": {"sport": "tennis", "pts": 800, "tier": "amateur"},
            },
            "skillDna": None,
        },
        {
            "uid": "u2",
            "name": "Bob",
            "preferences": {"area": 101},
            "rankings": {
                "tennis": {"sport": "tennis", "pts": 600, "tier": "amateur"},
            },
            "skillDna": None,
        },
        {
            "uid": "u3",
            "name": "Carol",
            "preferences": {"area": 202},
            "rankings": {
                "tennis": {"sport": "tennis", "pts": 900, "tier": "intermediate"},
            },
            "skillDna": None,
        },
    ]
    docs = []
    for u in users:
        doc = MagicMock()
        doc.id = u["uid"]
        doc.to_dict.return_value = u
        docs.append(doc)
    return docs


def _mock_point_history_docs(uid: str, sport: str) -> list[MagicMock]:
    """Return mock point history entries."""
    history: dict[str, list[dict]] = {
        "u1": [
            {"delta": 30, "sport": "tennis", "createdAt": _NOW - timedelta(days=2)},
            {"delta": 20, "sport": "tennis", "createdAt": _NOW - timedelta(days=5)},
        ],
        "u2": [
            {"delta": -10, "sport": "tennis", "createdAt": _NOW - timedelta(days=1)},
        ],
        "u3": [
            {"delta": 40, "sport": "tennis", "createdAt": _NOW - timedelta(days=3)},
        ],
    }
    entries = history.get(uid, [])
    docs = []
    for e in entries:
        doc = MagicMock()
        doc.to_dict.return_value = e
        docs.append(doc)
    return docs


def _build_mock_client() -> MagicMock:
    """Build a mock Firestore client that returns region config, users, and point history."""
    client = MagicMock()

    region_doc = _mock_region_doc()
    user_docs = _mock_user_docs()

    # Stable collection mocks so repeated calls return the same object
    leaderboards_col = MagicMock()
    leaderboards_col.document = MagicMock(return_value=MagicMock())

    def get_document(doc_id: str) -> MagicMock:
        doc_mock = MagicMock()
        if doc_id == "regions":
            doc_mock.get.return_value = region_doc
        elif doc_id == "tierAverages":
            tier_avg_doc = MagicMock()
            tier_avg_doc.exists = False
            doc_mock.get.return_value = tier_avg_doc
            doc_mock.set = MagicMock()
        else:
            empty_doc = MagicMock()
            empty_doc.exists = False
            doc_mock.get.return_value = empty_doc
        return doc_mock

    def get_collection(name: str) -> MagicMock:
        if name == "leaderboards":
            return leaderboards_col
        col = MagicMock()
        if name == "config":
            col.document = get_document
        elif name == "users":
            col.stream.return_value = iter(user_docs)

            def user_document(uid: str) -> MagicMock:
                user_doc = MagicMock()

                def ph_collection(subcol_name: str) -> MagicMock:
                    ph_col = MagicMock()

                    def where_sport(field: str, op: str, value: str) -> MagicMock:
                        q1 = MagicMock()

                        def where_created(
                            field2: str, op2: str, value2: datetime
                        ) -> MagicMock:
                            q2 = MagicMock()
                            q2.stream.return_value = iter(
                                _mock_point_history_docs(uid, value)
                            )
                            return q2

                        q1.where = where_created
                        return q1

                    ph_col.where = where_sport
                    return ph_col

                user_doc.collection = ph_collection
                return user_doc

            col.document = user_document
        return col

    client.collection = get_collection
    client.batch.return_value = MagicMock()
    return client


class TestComputeLeaderboards:
    def test_returns_summary_with_snapshots(self) -> None:
        client = _build_mock_client()
        summary = compute_leaderboards(client, now=_NOW)
        assert summary["snapshots_written"] > 0
        assert summary["users_count"] == 3

    def test_processes_both_regions(self) -> None:
        client = _build_mock_client()
        summary = compute_leaderboards(client, now=_NOW)
        processed = summary["regions_processed"]
        # athens_tennis and thessaloniki_tennis
        assert "athens_tennis" in processed
        assert "thessaloniki_tennis" in processed

    def test_writes_leaderboard_documents(self) -> None:
        client = _build_mock_client()
        compute_leaderboards(client, now=_NOW)

        lb_col = client.collection("leaderboards")
        # Should have called document().set() for each region+sport combo
        assert lb_col.document.call_count >= 2

    def test_no_users_produces_no_snapshots(self) -> None:
        client = _build_mock_client()
        # Override users to return empty
        users_col = MagicMock()
        users_col.stream.return_value = iter([])
        original_collection = client.collection

        def override_collection(name: str) -> MagicMock:
            if name == "users":
                return users_col
            return original_collection(name)

        client.collection = override_collection

        summary = compute_leaderboards(client, now=_NOW)
        assert summary["snapshots_written"] == 0
        assert summary["users_count"] == 0


class TestScheduledHandlerKillSwitch:
    @patch("functions.scheduled.main.triggers_enabled", return_value=False)
    def test_skips_when_disabled(self, _mock_enabled: MagicMock) -> None:
        from functions.scheduled.main import handle_leaderboard_computation

        # Should not raise; just return silently
        handle_leaderboard_computation()
