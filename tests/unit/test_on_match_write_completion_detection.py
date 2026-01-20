from datetime import datetime, timezone

from functions.match_triggers.on_match_write import qualify_completion_match_write


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_scheduled_to_completed_qualifies() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    before = {
        "matchId": "m_201",
        "status": "scheduled",
        "finishedAt": None,
        "participantUids": ["u1", "u2"],
    }
    after = {
        "matchId": "m_201",
        "status": "completed",
        "finishedAt": _utc(2025, 1, 1, 13, 0),
        "participantUids": ["u1", "u2"],
    }

    result = qualify_completion_match_write(before, after, now)

    assert result.qualifies is True
    assert result.reason == "qualifies"
    assert result.match_id == "m_201"


def test_completed_to_completed_ignored() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    before = {
        "matchId": "m_202",
        "status": "completed",
        "finishedAt": _utc(2025, 1, 1, 13, 0),
        "participantUids": ["u1", "u2"],
    }
    after = {
        "matchId": "m_202",
        "status": "completed",
        "finishedAt": _utc(2025, 1, 1, 13, 0),
        "participantUids": ["u1", "u2"],
    }

    result = qualify_completion_match_write(before, after, now)

    assert result.qualifies is False
    assert result.reason == "already_completed"


def test_scheduled_to_cancelled_ignored() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    before = {
        "matchId": "m_203",
        "status": "scheduled",
        "participantUids": ["u1", "u2"],
    }
    after = {
        "matchId": "m_203",
        "status": "cancelled",
        "finishedAt": None,
        "participantUids": ["u1", "u2"],
    }

    result = qualify_completion_match_write(before, after, now)

    assert result.qualifies is False
    assert result.reason == "status_not_transitioned"


def test_scheduled_to_completed_missing_finished_at_ignored() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    before = {
        "matchId": "m_204",
        "status": "scheduled",
        "participantUids": ["u1", "u2"],
    }
    after = {
        "matchId": "m_204",
        "status": "completed",
        "finishedAt": None,
        "participantUids": ["u1", "u2"],
    }

    result = qualify_completion_match_write(before, after, now)

    assert result.qualifies is False
    assert result.reason == "finished_at_missing"
