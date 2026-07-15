"""Unit tests for tools/set_area_status.py (no Firestore emulator)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from tools.set_area_status import _parse_args, set_area_status


def _make_doc(doc_id: str) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id
    doc.reference = MagicMock()
    return doc


def _make_client() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Mock a firestore.Client whose ``collection().where().where()`` returns a
    query that yields docs via ``stream()``."""
    client = MagicMock(spec=firestore.Client)
    collection_mock = MagicMock()
    where_area_mock = MagicMock()
    where_status_mock = MagicMock()
    client.collection.return_value = collection_mock
    collection_mock.where.return_value = where_area_mock
    where_area_mock.where.return_value = where_status_mock
    batch_mock = MagicMock()
    client.batch.return_value = batch_mock
    return client, where_status_mock, batch_mock


class TestSetAreaStatus:
    def test_filters_by_area_and_from_status(self) -> None:
        client, where_status_mock, _ = _make_client()
        where_status_mock.stream.return_value = []

        set_area_status(client, "lavrio", "hidden", "live")

        collection_mock = client.collection.return_value
        client.collection.assert_called_once_with("venues")
        collection_mock.where.assert_called_once_with("area", "==", "lavrio")
        collection_mock.where.return_value.where.assert_called_once_with(
            "status", "==", "hidden"
        )

    def test_updates_matching_docs_and_returns_count(self) -> None:
        client, where_status_mock, batch_mock = _make_client()
        docs = [_make_doc("venue_a"), _make_doc("venue_b")]
        where_status_mock.stream.return_value = docs

        updated = set_area_status(client, "lavrio", "hidden", "live")

        assert updated == 2
        assert batch_mock.update.call_count == 2
        batch_mock.update.assert_any_call(docs[0].reference, {"status": "live"})
        batch_mock.update.assert_any_call(docs[1].reference, {"status": "live"})
        batch_mock.commit.assert_called()

    def test_does_not_touch_unverified_rows_in_same_area(self) -> None:
        """The ``status == from_status`` filter means unverified rows never
        appear in the query results at all -- this documents that contract."""
        client, where_status_mock, batch_mock = _make_client()
        # Only the hidden doc is returned by the (mocked) query -- an
        # unverified doc in the same area would never match `where("status",
        # "==", "hidden")`.
        hidden_doc = _make_doc("venue_hidden")
        where_status_mock.stream.return_value = [hidden_doc]

        updated = set_area_status(client, "lavrio", "hidden", "live")

        assert updated == 1
        batch_mock.update.assert_called_once_with(
            hidden_doc.reference, {"status": "live"}
        )

    def test_returns_zero_when_no_matches(self) -> None:
        client, where_status_mock, batch_mock = _make_client()
        where_status_mock.stream.return_value = []

        updated = set_area_status(client, "lavrio", "hidden", "live")

        assert updated == 0
        batch_mock.update.assert_not_called()

    def test_batches_writes_in_chunks(self) -> None:
        client, where_status_mock, batch_mock = _make_client()
        docs = [_make_doc(f"venue_{i}") for i in range(401)]
        where_status_mock.stream.return_value = docs

        updated = set_area_status(client, "lavrio", "hidden", "live")

        assert updated == 401
        # 400 triggers one intermediate commit, plus a final commit for the
        # remaining doc -- at least 2 commits total.
        assert client.batch.call_count >= 2
        assert batch_mock.commit.call_count >= 1


class TestParseArgs:
    def test_from_and_to_must_differ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["set_area_status.py", "--area=lavrio", "--from=hidden", "--to=hidden"],
        )
        with pytest.raises(SystemExit):
            _parse_args()

    def test_invalid_status_value_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["set_area_status.py", "--area=lavrio", "--from=bogus", "--to=live"],
        )
        with pytest.raises(SystemExit):
            _parse_args()

    def test_valid_args_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["set_area_status.py", "--area=lavrio", "--from=hidden", "--to=live"],
        )
        args = _parse_args()
        assert args.area == "lavrio"
        assert args.from_status == "hidden"
        assert args.to_status == "live"
        assert args.env == "emu"
