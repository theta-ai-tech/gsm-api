"""
Unit tests for qualify_ranking_recomputation (D5.1 qualification logic).

Unlike D2, this qualifies any * → completed transition
(including pending_confirmation → completed produced by SE-5).
"""

from datetime import datetime, timezone

from functions.match_triggers.on_match_write import qualify_ranking_recomputation


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


_NOW = _utc(2025, 1, 1, 12, 0)
_FINISHED = _utc(2025, 1, 1, 13, 0)


def _after(status: str, finished_at: datetime | None = _FINISHED) -> dict:
    return {
        "matchId": "m_001",
        "status": status,
        "finishedAt": finished_at,
        "participantUids": ["u1", "u2"],
        "sport": "tennis",
    }


def _before(status: str) -> dict:
    return {"matchId": "m_001", "status": status, "participantUids": ["u1", "u2"]}


class TestQualifyRankingRecomputation:
    def test_pending_confirmation_to_completed_qualifies(self) -> None:
        result = qualify_ranking_recomputation(
            _before("pending_confirmation"), _after("completed"), _NOW
        )
        assert result.qualifies is True
        assert result.reason == "qualifies"

    def test_scheduled_to_completed_qualifies(self) -> None:
        result = qualify_ranking_recomputation(
            _before("scheduled"), _after("completed"), _NOW
        )
        assert result.qualifies is True
        assert result.reason == "qualifies"

    def test_completed_to_completed_does_not_qualify(self) -> None:
        result = qualify_ranking_recomputation(
            _before("completed"), _after("completed"), _NOW
        )
        assert result.qualifies is False
        assert result.reason == "already_completed"

    def test_scheduled_to_disputed_does_not_qualify(self) -> None:
        result = qualify_ranking_recomputation(
            _before("scheduled"), _after("disputed", finished_at=None), _NOW
        )
        assert result.qualifies is False
        assert result.reason == "status_not_completed"

    def test_deleted_event_does_not_qualify(self) -> None:
        result = qualify_ranking_recomputation(_before("scheduled"), None, _NOW)
        assert result.qualifies is False
        assert result.reason == "deleted"

    def test_missing_finished_at_does_not_qualify(self) -> None:
        result = qualify_ranking_recomputation(
            _before("pending_confirmation"), _after("completed", finished_at=None), _NOW
        )
        assert result.qualifies is False
        assert result.reason == "finished_at_missing"

    def test_naive_finished_at_does_not_qualify(self) -> None:
        naive_dt = datetime(2025, 1, 1, 13, 0)  # no tzinfo
        result = qualify_ranking_recomputation(
            _before("pending_confirmation"),
            _after("completed", finished_at=naive_dt),
            _NOW,
        )
        assert result.qualifies is False
        assert result.reason == "finished_at_naive"
