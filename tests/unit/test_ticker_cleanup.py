"""Unit tests for the scheduled ticker TTL cleanup function."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from functions.scheduled.ticker_cleanup import cleanup_expired_ticker_events

_NOW = datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)


def _make_expired_docs(count: int) -> list[MagicMock]:
    """Create mock Firestore document snapshots with references."""
    docs = []
    for i in range(count):
        doc = MagicMock()
        doc.id = f"expired_{i}"
        doc.reference = MagicMock()
        docs.append(doc)
    return docs


def _build_mock_client(expired_doc_counts: list[int]) -> MagicMock:
    """
    Build a mock Firestore client.

    ``expired_doc_counts`` is a list of integers: each entry is the number
    of expired docs returned by successive query.limit().stream() calls.
    After all entries are exhausted, stream() returns empty.
    """
    client = MagicMock()
    ticker_col = MagicMock()
    client.collection.return_value = ticker_col

    where_mock = MagicMock()
    ticker_col.where.return_value = where_mock

    # Build the sequence of stream results
    stream_results: list[list[MagicMock]] = []
    for count in expired_doc_counts:
        stream_results.append(_make_expired_docs(count))
    # Final empty result to terminate the loop
    stream_results.append([])

    limit_mock = MagicMock()
    limit_mock.stream = MagicMock(side_effect=[iter(docs) for docs in stream_results])
    where_mock.limit.return_value = limit_mock

    batch_mock = MagicMock()
    client.batch.return_value = batch_mock

    return client


class TestCleanupExpiredTickerEvents:
    def test_deletes_expired_docs_single_batch(self) -> None:
        client = _build_mock_client([3])
        summary = cleanup_expired_ticker_events(client, now=_NOW)

        assert summary["total_deleted"] == 3
        # batch.delete should have been called 3 times
        batch = client.batch.return_value
        assert batch.delete.call_count == 3
        batch.commit.assert_called_once()

    def test_deletes_multiple_batches(self) -> None:
        # Simulate two full batches of 500 + a partial batch of 10
        client = _build_mock_client([500, 500, 10])
        summary = cleanup_expired_ticker_events(client, now=_NOW)

        assert summary["total_deleted"] == 1010
        batch = client.batch.return_value
        assert batch.commit.call_count == 3

    def test_no_expired_docs(self) -> None:
        client = _build_mock_client([])
        summary = cleanup_expired_ticker_events(client, now=_NOW)

        assert summary["total_deleted"] == 0
        batch = client.batch.return_value
        batch.commit.assert_not_called()

    def test_queries_with_expires_at_less_than_now(self) -> None:
        client = _build_mock_client([])
        cleanup_expired_ticker_events(client, now=_NOW)

        client.collection.assert_called_with("ticker")
        ticker_col = client.collection.return_value
        ticker_col.where.assert_called_once_with("expiresAt", "<", _NOW)

    def test_uses_default_now_when_not_provided(self) -> None:
        client = _build_mock_client([])
        # Just verify it doesn't crash when now is not provided
        summary = cleanup_expired_ticker_events(client)
        assert summary["total_deleted"] == 0


class TestTickerCleanupScheduledHandler:
    @patch("functions.scheduled.main.triggers_enabled", return_value=False)
    def test_skips_when_disabled(self, _mock_enabled: MagicMock) -> None:
        from functions.scheduled.main import handle_ticker_cleanup

        # Should not raise; just return silently
        handle_ticker_cleanup()

    @patch("functions.scheduled.main.triggers_enabled", return_value=True)
    @patch("functions.scheduled.main.cleanup_expired_ticker_events")
    @patch("functions.scheduled.main.firestore")
    def test_calls_cleanup_when_enabled(
        self,
        mock_firestore: MagicMock,
        mock_cleanup: MagicMock,
        _mock_enabled: MagicMock,
    ) -> None:
        mock_cleanup.return_value = {"total_deleted": 5}
        mock_client = MagicMock()
        mock_firestore.Client.return_value = mock_client

        from functions.scheduled.main import handle_ticker_cleanup

        handle_ticker_cleanup()

        mock_cleanup.assert_called_once_with(mock_client)
