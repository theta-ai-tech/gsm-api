from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.league_triggers.on_league_member_write import (
    handle_league_member_removal,
    handle_league_member_upsert,
)
from functions.logging_utils import log_event
from functions.runtime_flags import triggers_enabled


def handle_league_member_write_upsert_summary(
    client: firestore.Client,
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    if not triggers_enabled():
        log_event(
            trigger="onLeagueMemberWrite.D3.1",
            action="ignore",
            leagueId=league_id,
            reason="triggers_disabled",
            changed=False,
            processed_count=1,
            ignored_count=1,
            writes_count=0,
        )
        return
    handle_league_member_upsert(client=client, league_id=league_id, before=before, after=after)


def handle_league_member_write_remove_summary(
    client: firestore.Client,
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    if not triggers_enabled():
        log_event(
            trigger="onLeagueMemberWrite.D3.2",
            action="ignore",
            leagueId=league_id,
            reason="triggers_disabled",
            changed=False,
            processed_count=1,
            ignored_count=1,
            writes_count=0,
        )
        return
    handle_league_member_removal(client=client, league_id=league_id, before=before, after=after)
