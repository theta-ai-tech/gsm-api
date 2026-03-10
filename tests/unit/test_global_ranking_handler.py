"""
Unit tests for handle_match_write_recompute_global_ranking (D5.1 handler).

Firestore client is fully mocked; no emulator needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.scoring_triggers.main import handle_match_write_recompute_global_ranking

_NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
_FINISHED = datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc)

SPORT = "tennis"


def _after(status: str = "completed", sport: str = SPORT) -> dict:
    return {
        "matchId": "m_001",
        "status": status,
        "finishedAt": _FINISHED,
        "participantUids": ["u1", "u2"],
        "sport": sport,
    }


def _before(status: str = "pending_confirmation") -> dict:
    return {"matchId": "m_001", "status": status, "participantUids": ["u1", "u2"]}


def _make_doc_snap(uid: str, pts: int) -> MagicMock:
    snap = MagicMock()
    snap.id = uid
    snap.to_dict.return_value = {"rankings": {SPORT: {"pts": pts}}}
    return snap


def _make_client(snaps: list[MagicMock]) -> MagicMock:
    client = MagicMock()
    # order_by().stream() returns the snapshot list
    client.collection.return_value.order_by.return_value.stream.return_value = iter(
        snaps
    )
    mock_batch = MagicMock()
    client.batch.return_value = mock_batch
    return client


class TestKillSwitch:
    def test_disabled_trigger_returns_early_without_writes(self) -> None:
        client = _make_client([])
        with patch(
            "functions.scoring_triggers.main.triggers_enabled", return_value=False
        ):
            handle_match_write_recompute_global_ranking(
                client, _before(), _after(), now=_NOW
            )
        client.batch.assert_not_called()


class TestNonQualifyingEvents:
    def test_already_completed_is_skipped(self) -> None:
        client = _make_client([])
        handle_match_write_recompute_global_ranking(
            client, _before("completed"), _after("completed"), now=_NOW
        )
        client.batch.assert_not_called()

    def test_disputed_status_is_skipped(self) -> None:
        after = {**_after(), "status": "disputed"}
        client = _make_client([])
        handle_match_write_recompute_global_ranking(client, _before(), after, now=_NOW)
        client.batch.assert_not_called()

    def test_missing_sport_is_skipped(self) -> None:
        after = {k: v for k, v in _after().items() if k != "sport"}
        client = _make_client([])
        handle_match_write_recompute_global_ranking(client, _before(), after, now=_NOW)
        client.batch.assert_not_called()


class TestQualifyingEvent:
    def test_completion_triggers_ranking_writes(self) -> None:
        snaps = [_make_doc_snap("u1", 2500), _make_doc_snap("u2", 2100)]
        client = _make_client(snaps)

        handle_match_write_recompute_global_ranking(
            client, _before(), _after(), now=_NOW
        )

        mock_batch = client.batch.return_value
        assert mock_batch.update.call_count == 2
        mock_batch.commit.assert_called_once()

    def test_pending_confirmation_to_completed_qualifies(self) -> None:
        snaps = [_make_doc_snap("u1", 2500)]
        client = _make_client(snaps)

        handle_match_write_recompute_global_ranking(
            client, _before("pending_confirmation"), _after(), now=_NOW
        )

        mock_batch = client.batch.return_value
        assert mock_batch.update.call_count == 1

    def test_globalRanking_written_in_pts_desc_order(self) -> None:
        # u2 has more pts → should get rank 1
        snaps = [_make_doc_snap("u2", 2500), _make_doc_snap("u1", 2100)]
        client = _make_client(snaps)

        # Capture update calls to verify rank values
        written: dict[str, int] = {}

        def _capture_update(ref: MagicMock, data: dict) -> None:
            uid = ref.id if hasattr(ref, "id") else str(ref)
            rank = data.get(f"rankings.{SPORT}.globalRanking")
            if rank is not None:
                written[uid] = rank

        mock_batch = client.batch.return_value
        mock_batch.update.side_effect = _capture_update

        # document() must return a mock with the correct .id
        def _doc_ref(uid: str) -> MagicMock:
            ref = MagicMock()
            ref.id = uid
            return ref

        client.collection.return_value.document.side_effect = _doc_ref

        handle_match_write_recompute_global_ranking(
            client, _before(), _after(), now=_NOW
        )

        assert written["u2"] == 1
        assert written["u1"] == 2

    def test_no_users_in_sport_writes_nothing(self) -> None:
        client = _make_client([])
        handle_match_write_recompute_global_ranking(
            client, _before(), _after(), now=_NOW
        )
        mock_batch = client.batch.return_value
        mock_batch.update.assert_not_called()
        mock_batch.commit.assert_not_called()

    def test_last_updated_uses_server_timestamp(self) -> None:
        """lastUpdated must be SERVER_TIMESTAMP, not a Python datetime."""
        snaps = [_make_doc_snap("u1", 2500)]
        client = _make_client(snaps)

        handle_match_write_recompute_global_ranking(
            client, _before(), _after(), now=_NOW
        )

        mock_batch = client.batch.return_value
        assert mock_batch.update.call_count == 1
        _, kwargs = mock_batch.update.call_args
        data: dict = mock_batch.update.call_args[0][1]
        assert data[f"rankings.{SPORT}.lastUpdated"] is firestore.SERVER_TIMESTAMP

    def test_last_updated_written_regardless_of_rank_change(self) -> None:
        """lastUpdated is always written, even when the ordinal position is unchanged."""
        snaps = [_make_doc_snap("u1", 2500)]
        client = _make_client(snaps)

        # Run twice — second run would produce the same rank but must still write lastUpdated
        for _ in range(2):
            client.collection.return_value.order_by.return_value.stream.return_value = (
                iter([_make_doc_snap("u1", 2500)])
            )
            handle_match_write_recompute_global_ranking(
                client, _before(), _after(), now=_NOW
            )

        assert client.batch.return_value.update.call_count == 2
