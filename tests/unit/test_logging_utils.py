from __future__ import annotations

import json
from datetime import datetime, timezone

from functions.logging_utils import format_event


def test_format_event_outputs_json_with_required_fields() -> None:
    rendered = format_event(
        trigger="onMatchWrite.D2",
        action="migrate_upcoming_to_recent",
        matchId="m_101",
        changed=True,
        at=datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    payload = json.loads(rendered)

    assert payload["trigger"] == "onMatchWrite.D2"
    assert payload["action"] == "migrate_upcoming_to_recent"
    assert payload["matchId"] == "m_101"
    assert payload["changed"] is True
    assert payload["at"] == "2030-01-01T12:00:00+00:00"
    assert payload["revision"] == "unknown"


def test_format_event_includes_explicit_runtime_revision(monkeypatch) -> None:
    monkeypatch.setenv("GSM_REVISION", "abc1234")
    rendered = format_event(trigger="onMatchWrite.D1", action="summary", changed=False)
    payload = json.loads(rendered)
    assert payload["revision"] == "abc1234"
