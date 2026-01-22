from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.league_triggers.on_league_member_write import (
    handle_league_member_removal,
    handle_league_member_upsert,
)


def handle_league_member_write_upsert_summary(
    client: firestore.Client,
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    handle_league_member_upsert(client=client, league_id=league_id, before=before, after=after)


def handle_league_member_write_remove_summary(
    client: firestore.Client,
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    handle_league_member_removal(client=client, league_id=league_id, before=before, after=after)
