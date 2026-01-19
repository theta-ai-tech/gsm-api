from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.match_triggers.on_match_write import (
    qualify_completion_match_write,
    qualify_upcoming_match_write,
)
from functions.match_triggers.upcoming_cache import (
    migrate_upcoming_to_completed_for_user,
    update_upcoming_cache_for_user,
)


def handle_match_write_update_upcoming_cache(
    client: firestore.Client,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    now: datetime | None = None,
) -> None:
    if now is None:
        now = datetime.now(timezone.utc)

    result = qualify_upcoming_match_write(before, after, now)
    if not result.qualifies or after is None or result.scheduled_at is None:
        return

    sport = after.get("sport")
    if not sport:
        return

    league_id = after.get("leagueId")
    court_id = after.get("courtId")

    for uid in result.participant_uids:
        update_upcoming_cache_for_user(
            client=client,
            uid=uid,
            match_id=result.match_id,
            scheduled_at=result.scheduled_at,
            sport=str(sport),
            league_id=league_id,
            court_id=court_id,
        )


def handle_match_write_migrate_on_completion(
    client: firestore.Client,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    now: datetime | None = None,
) -> None:
    if now is None:
        now = datetime.now(timezone.utc)

    result = qualify_completion_match_write(before, after, now)
    if not result.qualifies or after is None or result.finished_at is None:
        return

    sport = after.get("sport")
    if not sport:
        return

    league_id = after.get("leagueId")
    result_by_user = after.get("resultByUser") or {}
    score = after.get("score") or {}
    score_text = score.get("scoreText")

    for uid in result.participant_uids:
        migrate_upcoming_to_completed_for_user(
            client=client,
            uid=uid,
            match_id=result.match_id,
            finished_at=result.finished_at,
            sport=str(sport),
            league_id=league_id,
            result=result_by_user.get(uid),
            score_text=score_text,
        )
