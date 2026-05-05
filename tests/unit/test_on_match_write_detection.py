from datetime import datetime, timezone

from functions.match_triggers.on_match_write import qualify_upcoming_match_write


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_create_scheduled_future_qualifies() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    after = {
        "matchId": "m_101",
        "status": "scheduled",
        "scheduledAt": _utc(2025, 1, 2, 9, 0),
        "participantUids": ["u1", "u2"],
    }

    result = qualify_upcoming_match_write(None, after, now)

    assert result.qualifies is True
    assert result.reason == "qualifies"
    assert result.match_id == "m_101"


def test_create_scheduled_past_ignored() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    after = {
        "matchId": "m_102",
        "status": "scheduled",
        "scheduledAt": _utc(2024, 12, 31, 9, 0),
        "participantUids": ["u1", "u2"],
    }

    result = qualify_upcoming_match_write(None, after, now)

    assert result.qualifies is False
    assert result.reason == "scheduled_at_past"


def test_update_status_to_completed_ignored() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    before = {
        "matchId": "m_103",
        "status": "scheduled",
        "scheduledAt": _utc(2025, 1, 3, 9, 0),
        "participantUids": ["u1", "u2"],
    }
    after = {
        "matchId": "m_103",
        "status": "completed",
        "scheduledAt": _utc(2025, 1, 3, 9, 0),
        "participantUids": ["u1", "u2"],
    }

    result = qualify_upcoming_match_write(before, after, now)

    assert result.qualifies is False
    assert result.reason == "status_not_scheduled"


def test_update_scheduled_at_future_to_past_ignored() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    before = {
        "matchId": "m_104",
        "status": "scheduled",
        "scheduledAt": _utc(2025, 1, 4, 9, 0),
        "participantUids": ["u1", "u2"],
    }
    after = {
        "matchId": "m_104",
        "status": "scheduled",
        "scheduledAt": _utc(2024, 12, 30, 9, 0),
        "participantUids": ["u1", "u2"],
    }

    result = qualify_upcoming_match_write(before, after, now)

    assert result.qualifies is False
    assert result.reason == "scheduled_at_past"


def test_doubles_four_participant_uids_all_returned() -> None:
    """D1: qualify_upcoming_match_write must surface all 4 UIDs for a doubles match."""
    now = _utc(2025, 1, 1, 12, 0)
    after = {
        "matchId": "m_doubles_1",
        "status": "scheduled",
        "scheduledAt": _utc(2025, 1, 2, 9, 0),
        "participantUids": ["u1", "u2", "u3", "u4"],
    }

    result = qualify_upcoming_match_write(None, after, now)

    assert result.qualifies is True
    assert result.participant_uids == ["u1", "u2", "u3", "u4"]


def test_update_unrelated_field_only_is_no_op() -> None:
    now = _utc(2025, 1, 1, 12, 0)
    before = {
        "matchId": "m_105",
        "status": "scheduled",
        "scheduledAt": _utc(2025, 1, 5, 9, 0),
        "participantUids": ["u1", "u2"],
    }
    after = {
        "matchId": "m_105",
        "status": "scheduled",
        "scheduledAt": _utc(2025, 1, 5, 9, 0),
        "participantUids": ["u1", "u2"],
        "notes": "unrelated",
    }

    result = qualify_upcoming_match_write(before, after, now)

    assert result.qualifies is False
    assert result.reason == "no_op"
