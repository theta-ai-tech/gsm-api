from datetime import datetime, timezone

from functions.league_triggers.main import (
    handle_league_member_write_remove_summary,
    handle_league_member_write_upsert_summary,
)
from functions.match_triggers.main import (
    handle_match_write_migrate_on_completion,
    handle_match_write_update_upcoming_cache,
)


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_match_upcoming_handler_noops_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")

    called = {"value": False}

    def _should_not_call(**kwargs):
        called["value"] = True
        return True

    monkeypatch.setattr(
        "functions.match_triggers.main.update_upcoming_cache_for_user", _should_not_call
    )

    handle_match_write_update_upcoming_cache(
        client=object(),
        before=None,
        after={
            "matchId": "m1",
            "status": "scheduled",
            "scheduledAt": _utc(2030, 1, 1, 10, 0),
            "participantUids": ["u1"],
            "sport": "padel",
        },
        now=_utc(2029, 1, 1, 10, 0),
    )

    assert called["value"] is False


def test_match_completion_handler_noops_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")

    called = {"value": False}

    def _should_not_call(**kwargs):
        called["value"] = True
        return True

    monkeypatch.setattr(
        "functions.match_triggers.main.migrate_upcoming_to_completed_for_user",
        _should_not_call,
    )

    handle_match_write_migrate_on_completion(
        client=object(),
        before={
            "matchId": "m2",
            "status": "scheduled",
            "participantUids": ["u1"],
            "sport": "padel",
        },
        after={
            "matchId": "m2",
            "status": "completed",
            "finishedAt": _utc(2030, 1, 1, 12, 0),
            "participantUids": ["u1"],
            "sport": "padel",
        },
        now=_utc(2030, 1, 1, 12, 1),
    )

    assert called["value"] is False


def test_league_handlers_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")

    called = {"upsert": False, "remove": False}

    def _upsert(**kwargs):
        called["upsert"] = True

    def _remove(**kwargs):
        called["remove"] = True

    monkeypatch.setattr(
        "functions.league_triggers.main.handle_league_member_upsert", _upsert
    )
    monkeypatch.setattr(
        "functions.league_triggers.main.handle_league_member_removal", _remove
    )

    handle_league_member_write_upsert_summary(
        client=object(),
        league_id="l1",
        before=None,
        after={"uid": "u1", "status": "active", "role": "player"},
    )
    handle_league_member_write_remove_summary(
        client=object(),
        league_id="l1",
        before={"uid": "u1", "status": "active"},
        after=None,
    )

    assert called["upsert"] is False
    assert called["remove"] is False
